"""Consultor de etapas: o LLM sugere e o código valida e calcula.

- Escolhas (raça, classe...): o LLM escolhe um id; o schema só aceita ids reais do pack.
- Atributos: o LLM só ORDENA os atributos por prioridade; os valores saem do alocador.
- Perícias e textos: o LLM sugere; as quantidades e os limites são checados aqui.
"""

from dataclasses import dataclass
from typing import Any

from rpg_agent.application.errors import StepPreconditionError
from rpg_agent.application.rendering import PromptRenderer
from rpg_agent.application.step_models import (
    ChoiceProposal,
    RankingProposal,
    SkillsProposal,
    TextProposal,
    choice_schema,
    ranking_schema,
    skills_schema,
    text_schema,
)
from rpg_agent.application.structured import GenerationReport, StructuredGenerator
from rpg_agent.domain.allocator import AllocationError, allocate_by_ranking
from rpg_agent.domain.dice import DiceRoller
from rpg_agent.domain.engine import compute_sheet
from rpg_agent.domain.models.character import Character
from rpg_agent.domain.rule_system import AllocationRule, RulePack, StepDef
from rpg_agent.ports.llm import LLMPort, Message

_ZERO_REPORT = GenerationReport(attempts=0, latency_s=0.0, prompt_tokens=0, completion_tokens=0)
_FALLBACK_REASON = "padrão: o modelo não respondeu de forma válida"

_METHOD_LABELS = {
    "point_buy": "compra de pontos",
    "standard_array": "conjunto padrão de valores",
    "roll": "rolagem de dados",
    "free": "livre",
}
# campo narrativo -> (rótulo, nº máx. de sugestões, mín. e máx. de caracteres, orientação)
_TEXT_RULES = {
    "name": ("nome", 3, 2, 60, "Cada sugestão é um nome completo."),
    "concept": (
        "conceito",
        3,
        10,
        300,
        "Cada sugestão é uma frase curta que descreve o personagem.",
    ),
    "background": (
        "história",
        2,
        80,
        1200,
        "Cada sugestão é um texto de 2 a 4 frases com origem, motivação e gancho de aventura.",
    ),
}


@dataclass(frozen=True)
class ChoiceSuggestion:
    step_id: str
    choice_id: str
    option_id: str
    reason: str
    report: GenerationReport


@dataclass(frozen=True)
class AttributesSuggestion:
    step_id: str
    method: str
    ranking: list[str]
    scores: dict[str, int]
    reason: str
    report: GenerationReport


@dataclass(frozen=True)
class SkillsSuggestion:
    step_id: str
    skill_ids: list[str]
    reason: str
    report: GenerationReport


@dataclass(frozen=True)
class TextSuggestion:
    step_id: str
    field: str
    suggestions: list[str]
    report: GenerationReport


StepSuggestion = ChoiceSuggestion | AttributesSuggestion | SkillsSuggestion | TextSuggestion


class StepAdvisor:
    def __init__(
        self,
        llm: LLMPort,
        renderer: PromptRenderer | None = None,
        max_retries: int = 2,
        roller: DiceRoller | None = None,
    ) -> None:
        self._renderer = renderer or PromptRenderer()
        self._generator = StructuredGenerator(llm, self._renderer, max_retries)
        self._roller = roller or DiceRoller()

    def suggest(
        self,
        pack: RulePack,
        character: Character,
        step_id: str,
        user_input: str = "",
    ) -> StepSuggestion:
        if character.system_id != pack.id:
            raise StepPreconditionError(
                f"ficha do sistema {character.system_id!r}, mas o pack é {pack.id!r}"
            )
        step = next((s for s in pack.steps if s.id == step_id), None)
        if step is None:
            raise StepPreconditionError(f"etapa desconhecida: {step_id!r}")

        if step.kind == "choice":
            return self._suggest_choice(pack, character, step, user_input)
        if step.kind == "attributes":
            return self._suggest_attributes(pack, character, step, user_input)
        if step.kind == "skills":
            return self._suggest_skills(pack, character, step, user_input)
        return self._suggest_text(pack, character, step, user_input)

    def default_suggestion(
        self, pack: RulePack, character: Character, step_id: str
    ) -> StepSuggestion | None:
        """Uma sugestão determinística, sem LLM, para quando o modelo falha repetidamente.

        Só existe para etapas de escolha (primeira opção do pack) e de atributos (ordem de
        prioridade da classe já escolhida, ou a ordem dos atributos no pack se nenhuma classe
        foi escolhida ainda). Perícias e campos narrativos não têm um padrão razoável: `None`.
        """
        if character.system_id != pack.id:
            raise StepPreconditionError(
                f"ficha do sistema {character.system_id!r}, mas o pack é {pack.id!r}"
            )
        step = next((s for s in pack.steps if s.id == step_id), None)
        if step is None:
            raise StepPreconditionError(f"etapa desconhecida: {step_id!r}")

        if step.kind == "choice":
            return self._default_choice(pack, step)
        if step.kind == "attributes":
            return self._default_attributes(pack, character, step)
        return None

    def _default_choice(self, pack: RulePack, step: StepDef) -> ChoiceSuggestion | None:
        choice = pack.get_choice(step.target or "")
        if choice is None or not choice.options:
            return None
        first = choice.options[0]
        return ChoiceSuggestion(step.id, choice.id, first.id, _FALLBACK_REASON, _ZERO_REPORT)

    def _default_attributes(
        self, pack: RulePack, character: Character, step: StepDef
    ) -> AttributesSuggestion | None:
        try:
            rule = self._select_rule(pack, character)
        except StepPreconditionError:
            return None  # sem método escolhido, não há como propor um padrão
        ranking = list(compute_sheet(pack, character).priority_attributes) or pack.attribute_ids()
        rolled = self._roller.roll_scores(len(ranking)) if rule.method == "roll" else None
        try:
            scores = allocate_by_ranking(rule, ranking, rolled)
        except AllocationError:
            return None
        return AttributesSuggestion(
            step.id, rule.method, ranking, scores, _FALLBACK_REASON, _ZERO_REPORT
        )

    # ------------------------------------------------------------ escolhas
    def _suggest_choice(
        self, pack: RulePack, character: Character, step: StepDef, user_input: str
    ) -> ChoiceSuggestion:
        choice = pack.get_choice(step.target or "")
        if choice is None:
            raise StepPreconditionError(f"etapa {step.id!r} sem escolha associada")

        option_ids = [o.id for o in choice.options]
        attr_names = {a.id: a.name for a in pack.attributes}
        skill_names = {s.id: s.name for s in pack.skills}
        options = [
            {
                "id": o.id,
                "name": o.name,
                "description": o.description,
                "bonuses": ", ".join(
                    f"{attr_names.get(a, a)} {b:+d}" for a, b in o.attribute_bonuses.items()
                ),
                "skills": ", ".join(skill_names.get(s, s) for s in o.granted_skills),
            }
            for o in choice.options
        ]
        messages = self._messages(
            pack,
            character,
            "step_choice.j2",
            step_title=step.title,
            step_prompt=step.prompt,
            choice_name=choice.name,
            options=options,
            user_input=user_input,
        )

        def check(p: ChoiceProposal) -> list[str]:
            if p.choice_id in option_ids:
                return []
            return [f"choice_id {p.choice_id!r} é inválido; use um destes: {option_ids}"]

        generated = self._generator.generate(
            messages, ChoiceProposal, schema=choice_schema(option_ids), check=check
        )
        value = generated.value
        return ChoiceSuggestion(step.id, choice.id, value.choice_id, value.reason, generated.report)

    # ------------------------------------------------------------ atributos
    def _suggest_attributes(
        self, pack: RulePack, character: Character, step: StepDef, user_input: str
    ) -> AttributesSuggestion:
        rule = self._select_rule(pack, character)
        attr_ids = pack.attribute_ids()
        attr_names = {a.id: a.name for a in pack.attributes}
        priority = list(compute_sheet(pack, character).priority_attributes)
        priority_hint = ", ".join(attr_names[a] for a in priority)
        rolled = self._roller.roll_scores(len(attr_ids)) if rule.method == "roll" else None

        messages = self._messages(
            pack,
            character,
            "step_attributes.j2",
            step_title=step.title,
            step_prompt=step.prompt,
            method_label=_METHOD_LABELS[rule.method],
            attribute_options=[{"id": a.id, "name": a.name} for a in pack.attributes],
            priority_hint=priority_hint,
            user_input=user_input,
        )

        def check(p: RankingProposal) -> list[str]:
            if sorted(p.ranking) != sorted(attr_ids):
                return [f"o ranking deve conter cada um destes ids exatamente uma vez: {attr_ids}"]
            if priority and priority[0] not in p.ranking[:3]:
                main = attr_names[priority[0]]
                return [f"o atributo principal da classe ({main}) deve estar entre os 3 primeiros"]
            return []

        generated = self._generator.generate(
            messages, RankingProposal, schema=ranking_schema(attr_ids), check=check
        )
        try:
            scores = allocate_by_ranking(rule, generated.value.ranking, rolled)
        except AllocationError as exc:
            raise StepPreconditionError(str(exc)) from exc
        value = generated.value
        return AttributesSuggestion(
            step.id, rule.method, value.ranking, scores, value.reason, generated.report
        )

    @staticmethod
    def _select_rule(pack: RulePack, character: Character) -> AllocationRule:
        methods = [r.method for r in pack.attribute_rules]
        if character.attribute_method is not None:
            rule = pack.get_attribute_rule(character.attribute_method)
            if rule is None:
                raise StepPreconditionError(f"método não permitido: {character.attribute_method!r}")
            return rule
        if len(pack.attribute_rules) == 1:
            return pack.attribute_rules[0]
        raise StepPreconditionError(f"defina attribute_method antes (opções: {methods})")

    # ------------------------------------------------------------ perícias
    def _suggest_skills(
        self, pack: RulePack, character: Character, step: StepDef, user_input: str
    ) -> SkillsSuggestion:
        sheet = compute_sheet(pack, character)
        budget = sheet.skill_budget
        if budget is None or budget <= 0:
            raise StepPreconditionError("defina a classe antes de escolher perícias")
        skill_ids = list(sheet.allowed_skills)  # só as perícias que as regras permitem
        count = min(budget, len(skill_ids))

        attr_names = {a.id: a.name for a in pack.attributes}
        messages = self._messages(
            pack,
            character,
            "step_skills.j2",
            step_title=step.title,
            step_prompt=step.prompt,
            skill_options=[
                {"id": s.id, "name": s.name, "attribute": attr_names.get(s.attribute or "", "")}
                for s in pack.skills
                if s.id in skill_ids
            ],
            count=count,
            user_input=user_input,
        )

        def check(p: SkillsProposal) -> list[str]:
            problems: list[str] = []
            unknown = [s for s in p.skill_ids if s not in skill_ids]
            if unknown:
                problems.append(f"perícias não permitidas: {unknown}; use apenas {skill_ids}")
            if len(set(p.skill_ids)) != len(p.skill_ids):
                problems.append("há perícias repetidas")
            if len(p.skill_ids) != count:
                problems.append(f"escolha exatamente {count} perícias, não {len(p.skill_ids)}")
            return problems

        generated = self._generator.generate(
            messages, SkillsProposal, schema=skills_schema(skill_ids, count), check=check
        )
        value = generated.value
        return SkillsSuggestion(step.id, value.skill_ids, value.reason, generated.report)

    # ------------------------------------------------------------ textos
    def _suggest_text(
        self, pack: RulePack, character: Character, step: StepDef, user_input: str
    ) -> TextSuggestion:
        if step.fills is None:
            raise StepPreconditionError(f"etapa {step.id!r} sem campo narrativo")
        label, count, min_chars, max_chars, guidance = _TEXT_RULES[step.fills]
        messages = self._messages(
            pack,
            character,
            "step_text.j2",
            step_title=step.title,
            step_prompt=step.prompt,
            field_label=label,
            count=count,
            min_chars=min_chars,
            max_chars=max_chars,
            guidance=guidance,
            user_input=user_input,
        )

        def check(p: TextProposal) -> list[str]:
            problems: list[str] = []
            if len(p.suggestions) > count:
                problems.append(f"no máximo {count} sugestões")
            if any(not s.strip() for s in p.suggestions):
                problems.append("há sugestões vazias")
            if any(0 < len(s.strip()) < min_chars for s in p.suggestions):
                problems.append(f"cada sugestão deve ter pelo menos {min_chars} caracteres")
            if any(len(s) > max_chars for s in p.suggestions):
                problems.append(f"cada sugestão deve ter no máximo {max_chars} caracteres")
            return problems

        generated = self._generator.generate(
            messages, TextProposal, schema=text_schema(count, min_chars), check=check
        )
        suggestions = [s.strip() for s in generated.value.suggestions]
        return TextSuggestion(step.id, step.fills, suggestions, generated.report)

    # ------------------------------------------------------------ prompts
    def _messages(
        self, pack: RulePack, character: Character, template: str, **context: Any
    ) -> list[Message]:
        sheet = compute_sheet(pack, character)
        chosen = []
        for choice_id, option_id in character.choices.items():
            choice = pack.get_choice(choice_id)
            option = pack.get_option(choice_id, option_id)
            if choice is not None and option is not None:
                chosen.append({"choice": choice.name, "option": option.name})
        attributes = [
            {"name": a.name, "value": sheet.final_attributes[a.id]}
            for a in pack.attributes
            if a.id in sheet.final_attributes
        ]
        base = {"concept": character.concept, "chosen": chosen, "attributes": attributes}
        return [
            Message("system", self._renderer.render("system.j2", system_name=pack.name)),
            Message("user", self._renderer.render(template, **base, **context)),
        ]
