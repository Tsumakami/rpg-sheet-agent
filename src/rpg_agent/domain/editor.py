"""Editor de ficha: o único caminho para alterar uma ficha sem quebrar as regras.

Cada alteração gera uma ficha NOVA (a original nunca é modificada) e só é aceita se
o resultado passar na validação do Rule Pack. Do contrário, levanta `RuleViolationError`
e a ficha original continua intacta.

Alterar uma escolha pode invalidar etapas já concluídas (ex.: trocar de classe depois de
escolher as perícias). Nesse caso essas etapas são REABERTAS (dados limpos e tiradas de
`completed_steps`) e o resultado informa quais foram, em vez de deixar a ficha inconsistente.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from rpg_agent.domain.issues import Issue, Severity
from rpg_agent.domain.models.character import Character
from rpg_agent.domain.rule_system import RulePack, StepDef
from rpg_agent.domain.validators import validate_character

NARRATIVE_FIELDS = ("name", "concept", "background")


class RuleViolationError(ValueError):
    """A alteração violaria as regras do sistema."""

    def __init__(self, issues: Sequence[Issue]) -> None:
        self.issues = list(issues)
        super().__init__("; ".join(i.message for i in self.issues))


@dataclass(frozen=True)
class EditResult:
    character: Character
    reopened_steps: tuple[str, ...] = ()  # etapas invalidadas pela alteração
    warnings: tuple[Issue, ...] = ()


def _updated(character: Character, **changes: Any) -> Character:
    """Cópia revalidada pelo Pydantic (tipos corretos) com as mudanças aplicadas."""
    return Character.model_validate({**character.model_dump(), **changes})


class SheetEditor:
    def __init__(self, pack: RulePack) -> None:
        self.pack = pack

    # ------------------------------------------------------------ alterações
    def set_choice(self, character: Character, choice_id: str, option_id: str) -> EditResult:
        step = self._find_step(
            lambda s: s.kind == "choice" and s.target == choice_id, f"a escolha {choice_id!r}"
        )
        candidate = _updated(character, choices={**character.choices, choice_id: option_id})
        return self._commit(candidate, step)

    def set_attributes(
        self, character: Character, method: str, scores: Mapping[str, int]
    ) -> EditResult:
        step = self._find_step(lambda s: s.kind == "attributes", "os atributos")
        candidate = _updated(character, attributes=dict(scores), attribute_method=method)
        return self._commit(candidate, step)

    def set_skills(self, character: Character, skills: Mapping[str, int]) -> EditResult:
        step = self._find_step(lambda s: s.kind == "skills", "as perícias")
        return self._commit(_updated(character, skills=dict(skills)), step)

    def set_text(self, character: Character, field: str, text: str) -> EditResult:
        if field not in NARRATIVE_FIELDS:
            raise RuleViolationError([Issue("unknown_field", f"Campo desconhecido: {field!r}.")])
        step = self._find_step(
            lambda s: s.kind == "narrative" and s.fills == field, f"o campo {field!r}"
        )
        cleaned = text.strip()
        if not cleaned:
            raise RuleViolationError(
                [Issue("narrative_empty", f"O campo {field!r} não pode ficar vazio.", field)]
            )
        return self._commit(_updated(character, **{field: cleaned}), step)

    def finalize(self, character: Character) -> Character:
        """Confirma que a ficha está COMPLETA e válida; senão levanta RuleViolationError."""
        issues = validate_character(self.pack, character, require_complete=True)
        errors = [i for i in issues if i.severity is Severity.ERROR]
        if errors:
            raise RuleViolationError(errors)
        return character

    # ------------------------------------------------------------ internos
    def _find_step(self, predicate: Callable[[StepDef], bool], label: str) -> StepDef:
        step = next((s for s in self.pack.steps if predicate(s)), None)
        if step is None:
            raise RuleViolationError(
                [Issue("unknown_step", f"O sistema {self.pack.id!r} não tem etapa para {label}.")]
            )
        return step

    def _commit(self, candidate: Character, step: StepDef) -> EditResult:
        completed = list(candidate.completed_steps)
        if step.id not in completed:
            completed.append(step.id)
        candidate = _updated(candidate, completed_steps=completed)

        reopened: list[str] = []
        for _ in range(len(self.pack.steps) + 1):
            issues = validate_character(self.pack, candidate)
            errors = [i for i in issues if i.severity is Severity.ERROR]
            if not errors:
                warnings = tuple(i for i in issues if i.severity is Severity.WARNING)
                return EditResult(candidate, tuple(reopened), warnings)

            culprits = [self.step_id_for(i) for i in errors]
            # erro na própria etapa editada (ou sem etapa associada): a alteração é recusada
            if any(c is None or c == step.id for c in culprits):
                raise RuleViolationError(errors)
            # erro em OUTRAS etapas já concluídas: elas são reabertas
            for step_id in dict.fromkeys(c for c in culprits if c is not None):
                if step_id in reopened:
                    raise RuleViolationError(errors)
                candidate = self._reopen(candidate, step_id)
                reopened.append(step_id)
        raise RuleViolationError(errors)

    def step_id_for(self, issue: Issue) -> str | None:
        """A qual etapa do pack um problema de validação se refere (None se nenhuma)."""
        root, _, rest = issue.path.partition(".")
        for s in self.pack.steps:
            if root in ("attributes", "attribute_method") and s.kind == "attributes":
                return s.id
            if root == "skills" and s.kind == "skills":
                return s.id
            if root == "choices" and s.kind == "choice" and s.target == rest:
                return s.id
            if root in NARRATIVE_FIELDS and s.kind == "narrative" and s.fills == root:
                return s.id
        return None

    def _reopen(self, character: Character, step_id: str) -> Character:
        step = next(s for s in self.pack.steps if s.id == step_id)
        changes: dict[str, Any] = {
            "completed_steps": [s for s in character.completed_steps if s != step_id]
        }
        if step.kind == "skills":
            changes["skills"] = {}
        elif step.kind == "attributes":
            changes.update(attributes={}, attribute_method=None)
        elif step.kind == "choice":
            changes["choices"] = {k: v for k, v in character.choices.items() if k != step.target}
        elif step.fills is not None:
            changes[step.fills] = ""
        return _updated(character, **changes)
