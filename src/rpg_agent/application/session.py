"""Sessão de criação de personagem: percorre as etapas do pack, aplicando sugestões do
StepAdvisor através do SheetEditor, com desfazer/refazer e etapas puláveis.

A ficha nunca é alterada no lugar: cada ação bem-sucedida empilha um novo estado (a ficha
mais a posição na lista de etapas), o que dá undo/redo sem nenhuma lógica extra de reversão.
O jogador pode pular qualquer etapa, inclusive obrigatórias; `finalize` (via SheetEditor) só
aceita a ficha se ela estiver completa, e `missing_steps` traduz o que falta em etapas.
"""

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from rpg_agent.application.apply import apply_suggestion
from rpg_agent.application.errors import (
    ChoiceNotFoundError,
    LLMOutputError,
    StepPreconditionError,
)
from rpg_agent.application.step_advisor import StepAdvisor, StepSuggestion
from rpg_agent.domain.dice import DiceRoller
from rpg_agent.domain.editor import EditResult, RuleViolationError, SheetEditor
from rpg_agent.domain.models.character import Character
from rpg_agent.domain.rule_system import ChoiceDef, RulePack, StepDef
from rpg_agent.ports.llm import LLMPort


def _normalize(text: str) -> str:
    """minúsculas e sem acentos, para casar texto livre do jogador sem exigir exatidão."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).strip().lower()


def match_option(choice: ChoiceDef, text: str) -> str:
    """Casa texto livre do jogador com o id de uma opção da escolha, sem LLM.

    Tenta, nessa ordem: id exato, nome exato, depois um id ou nome que CONTENHA o texto
    (só aceito se for único). Tudo sem diferenciar maiúsculas/minúsculas nem acentos.
    """
    needle = _normalize(text)
    all_ids = [o.id for o in choice.options]
    if not needle:
        raise ChoiceNotFoundError(text, all_ids)

    by_id = {_normalize(o.id): o.id for o in choice.options}
    if needle in by_id:
        return by_id[needle]
    by_name = {_normalize(o.name): o.id for o in choice.options}
    if needle in by_name:
        return by_name[needle]

    contains = {
        o.id for o in choice.options if needle in _normalize(o.name) or needle in _normalize(o.id)
    }
    if len(contains) == 1:
        return contains.pop()
    raise ChoiceNotFoundError(text, sorted(contains) if contains else all_ids)


@dataclass(frozen=True)
class SessionState:
    character: Character
    step_index: int  # posição em pack.steps da PRÓXIMA etapa a fazer


@dataclass(frozen=True)
class FallbackSuggestion:
    """O que `suggest_or_fallback` devolve quando o LLM esgota as tentativas sem sucesso.

    `default`, quando não é None, é uma StepSuggestion pronta para `accept()` (gerada sem
    LLM, de forma determinística). Quando é None, a etapa não tem um padrão razoável e só
    resta preencher manualmente (`choose`, `set_text`, `set_attributes` ou `set_skills`).
    """

    step_id: str
    attempts: int
    problems: tuple[str, ...]  # problemas da ÚLTIMA tentativa, para mostrar ao jogador/log
    default: StepSuggestion | None


class CharacterCreationSession:
    """Orquestra a criação de UM personagem; cada instância cobre uma sessão."""

    def __init__(
        self,
        pack: RulePack,
        llm: LLMPort,
        *,
        roller: DiceRoller | None = None,
        max_retries: int = 2,
    ) -> None:
        self.pack = pack
        self.advisor = StepAdvisor(llm, max_retries=max_retries, roller=roller)
        self.editor = SheetEditor(pack)
        self._past: list[SessionState] = [SessionState(Character(system_id=pack.id), 0)]
        self._future: list[SessionState] = []

    # ------------------------------------------------------------ estado
    @property
    def character(self) -> Character:
        return self._past[-1].character

    @property
    def step_index(self) -> int:
        return self._past[-1].step_index

    @property
    def current_step(self) -> StepDef | None:
        """A próxima etapa a fazer, ou None quando todas foram percorridas."""
        idx = self.step_index
        return self.pack.steps[idx] if idx < len(self.pack.steps) else None

    @property
    def is_finished(self) -> bool:
        return self.current_step is None

    @property
    def can_undo(self) -> bool:
        return len(self._past) > 1

    @property
    def can_redo(self) -> bool:
        return bool(self._future)

    # ------------------------------------------------------------ sugestão do LLM
    def suggest(self, user_input: str = "") -> StepSuggestion:
        """Pede ao StepAdvisor uma sugestão para a etapa atual (não altera a ficha)."""
        step = self._require_current_step()
        return self.advisor.suggest(self.pack, self.character, step.id, user_input)

    def suggest_or_fallback(self, user_input: str = "") -> StepSuggestion | FallbackSuggestion:
        """Como `suggest`, mas nunca levanta LLMOutputError.

        Se o modelo esgotar as tentativas, devolve um FallbackSuggestion no lugar, em vez de
        travar a sessão. Não altera a ficha nem avança a etapa em nenhum dos dois casos.
        """
        step = self._require_current_step()
        try:
            return self.advisor.suggest(self.pack, self.character, step.id, user_input)
        except LLMOutputError as exc:
            default = self.advisor.default_suggestion(self.pack, self.character, step.id)
            last = tuple(exc.problems_by_attempt[-1]) if exc.problems_by_attempt else ()
            return FallbackSuggestion(step.id, len(exc.problems_by_attempt), last, default)

    def accept(self, suggestion: StepSuggestion) -> EditResult:
        """Aplica a sugestão (via SheetEditor) e avança.

        Levanta RuleViolationError se a sugestão violar as regras; a ficha não muda.
        """
        self._require_current_step()
        result = apply_suggestion(self.editor, self.character, suggestion)
        self._advance(result.character)
        return result

    # ------------------------------------------------------------ edição manual (sem LLM)
    def choose(self, text: str) -> EditResult:
        """Escolhe uma opção pelo nome ou id (etapa kind=choice), sem chamar o LLM."""
        step = self._require_current_step()
        if step.kind != "choice" or step.target is None:
            raise StepPreconditionError(f"a etapa {step.id!r} não é uma escolha")
        choice = self.pack.get_choice(step.target)
        if choice is None:  # pragma: no cover - garantido pela integridade do RulePack
            raise StepPreconditionError(f"escolha {step.target!r} não existe no pack")
        option_id = match_option(choice, text)
        result = self.editor.set_choice(self.character, choice.id, option_id)
        self._advance(result.character)
        return result

    def set_text(self, text: str) -> EditResult:
        """Preenche o campo narrativo da etapa atual (kind=narrative), sem LLM."""
        step = self._require_current_step()
        if step.kind != "narrative" or step.fills is None:
            raise StepPreconditionError(f"a etapa {step.id!r} não é um campo narrativo")
        result = self.editor.set_text(self.character, step.fills, text)
        self._advance(result.character)
        return result

    def set_attributes(self, method: str, scores: Mapping[str, int]) -> EditResult:
        """Define os atributos diretamente (etapa kind=attributes), sem LLM."""
        step = self._require_current_step()
        if step.kind != "attributes":
            raise StepPreconditionError(f"a etapa {step.id!r} não é de atributos")
        result = self.editor.set_attributes(self.character, method, scores)
        self._advance(result.character)
        return result

    def set_skills(self, skill_ids: Sequence[str]) -> EditResult:
        """Define as perícias escolhidas diretamente (etapa kind=skills), sem LLM."""
        step = self._require_current_step()
        if step.kind != "skills":
            raise StepPreconditionError(f"a etapa {step.id!r} não é de perícias")
        skills = dict.fromkeys(skill_ids, self.pack.skill_max)
        result = self.editor.set_skills(self.character, skills)
        self._advance(result.character)
        return result

    # ------------------------------------------------------------ pular / desfazer / refazer
    def skip(self) -> None:
        """Avança para a próxima etapa sem preencher a atual, mesmo que seja obrigatória."""
        self._require_current_step()
        self._push(SessionState(self.character, self.step_index + 1))

    def undo(self) -> None:
        if not self.can_undo:
            raise StepPreconditionError("não há nada para desfazer")
        self._future.append(self._past.pop())

    def redo(self) -> None:
        if not self.can_redo:
            raise StepPreconditionError("não há nada para refazer")
        self._past.append(self._future.pop())

    # ------------------------------------------------------------ finalização
    def finalize(self) -> Character:
        """Confirma a ficha; levanta RuleViolationError se faltar algo (ver `missing_steps`)."""
        return self.editor.finalize(self.character)

    def missing_steps(self) -> list[StepDef]:
        """O que falta para a ficha ficar completa, sem levantar exceção."""
        try:
            self.editor.finalize(self.character)
        except RuleViolationError as exc:
            ids = {self.editor.step_id_for(issue) for issue in exc.issues}
            return [s for s in self.pack.steps if s.id in ids]
        return []

    # ------------------------------------------------------------ internos
    def _require_current_step(self) -> StepDef:
        step = self.current_step
        if step is None:
            raise StepPreconditionError("todas as etapas já foram percorridas")
        return step

    def _advance(self, character: Character) -> None:
        self._push(SessionState(character, self.step_index + 1))

    def _push(self, state: SessionState) -> None:
        self._past.append(state)
        self._future.clear()  # uma ação nova descarta qualquer redo pendente
