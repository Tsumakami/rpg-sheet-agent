"""Schema declarativo de um Rule Pack (um sistema de RPG)."""

from collections import Counter
from collections.abc import Iterable
from typing import Annotated, Literal, Self, TypeGuard

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from rpg_agent.domain.expressions import ExpressionError, formula_names

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
Scalar = int | str
AllocationMethod = Literal["point_buy", "standard_array", "roll", "free"]
StepKind = Literal["narrative", "choice", "attributes", "skills"]
NarrativeField = Literal["name", "concept", "background"]


class _Model(BaseModel):
    # extra="forbid": erro de digitação no YAML falha cedo, em vez de ser ignorado.
    model_config = ConfigDict(extra="forbid", frozen=True)


class AttributeDef(_Model):
    id: Identifier
    name: str


class SkillDef(_Model):
    id: Identifier
    name: str
    attribute: Identifier | None = None


class OptionDef(_Model):
    id: Identifier
    name: str
    description: str = ""
    attribute_bonuses: dict[Identifier, int] = Field(default_factory=dict)
    # dados numéricos viram variáveis de fórmula: <escolha>_<campo> (ex.: class_hit_die)
    data: dict[Identifier, Scalar] = Field(default_factory=dict)
    # perícias que esta opção permite escolher (None = sem restrição). Ex.: lista da classe.
    allowed_skills: list[Identifier] | None = None
    # perícias que esta opção CONCEDE automaticamente (ex.: antecedente, traço racial)
    granted_skills: list[Identifier] = Field(default_factory=list)
    # listas concedidas por grupo (ex.: {saving_throws: [int, wis]}); ver DerivedDef.flag_from
    grants: dict[Identifier, list[Identifier]] = Field(default_factory=dict)
    # ordem recomendada de atributos (do mais ao menos importante) para esta opção
    priority_attributes: list[Identifier] | None = None


class ChoiceDef(_Model):
    id: Identifier
    name: str
    options: list[OptionDef] = Field(min_length=1)
    required: bool = True


class DerivedDef(_Model):
    id: Identifier
    name: str
    formula: str
    # True: calcula uma vez por atributo (variável `value`), gerando <atributo>_<id>
    per_attribute: bool = False
    # (só com per_attribute) grupo de `grants`; define a variável `granted` (1 ou 0) por atributo
    flag_from: Identifier | None = None


class AllocationRule(_Model):
    method: AllocationMethod
    min_score: int | None = None
    max_score: int | None = None
    budget: int | None = None
    costs: dict[int, int] = Field(default_factory=dict)
    array: list[int] = Field(default_factory=list)


class StepDef(_Model):
    id: Identifier
    title: str
    kind: StepKind
    target: Identifier | None = None  # id da escolha (kind=choice)
    fills: NarrativeField | None = None  # campo da ficha (kind=narrative)
    prompt: str = ""  # dica para o LLM / para o jogador


def is_number(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def numeric_fields(choice: ChoiceDef) -> set[str]:
    return {k for opt in choice.options for k, v in opt.data.items() if is_number(v)}


def _duplicates(ids: Iterable[str]) -> list[str]:
    return sorted(k for k, n in Counter(ids).items() if n > 1)


class RulePack(_Model):
    schema_version: Literal[1]
    id: Identifier
    name: str
    version: str
    license: str = ""
    attribution: str = ""

    attributes: list[AttributeDef] = Field(min_length=1)
    attribute_rules: list[AllocationRule] = Field(min_length=1)

    skills: list[SkillDef] = Field(default_factory=list)
    skill_min: int = 0
    skill_max: int = 1
    skill_budget: str | None = None
    # bônus de cada perícia: variáveis `value`, `proficient` (1/0) e derivados por atributo
    skill_modifier: str | None = None

    choices: list[ChoiceDef] = Field(default_factory=list)
    derived: list[DerivedDef] = Field(default_factory=list)
    steps: list[StepDef] = Field(min_length=1)

    # ------------------------------------------------------------ consultas
    def attribute_ids(self) -> list[str]:
        return [a.id for a in self.attributes]

    def skill_ids(self) -> list[str]:
        return [s.id for s in self.skills]

    def get_choice(self, choice_id: str) -> ChoiceDef | None:
        return next((c for c in self.choices if c.id == choice_id), None)

    def get_option(self, choice_id: str, option_id: str) -> OptionDef | None:
        choice = self.get_choice(choice_id)
        if choice is None:
            return None
        return next((o for o in choice.options if o.id == option_id), None)

    def get_attribute_rule(self, method: str) -> AllocationRule | None:
        return next((r for r in self.attribute_rules if r.method == method), None)

    # ------------------------------------------------- integridade (fail-fast)
    @model_validator(mode="after")
    def _check_integrity(self) -> Self:
        problems = self._problems()
        if problems:
            raise ValueError("Rule Pack inconsistente: " + "; ".join(problems))
        return self

    def _problems(self) -> list[str]:
        problems: list[str] = []
        attr_ids = set(self.attribute_ids())

        for label, ids in (
            ("atributo", self.attribute_ids()),
            ("perícia", self.skill_ids()),
            ("escolha", [c.id for c in self.choices]),
            ("derivado", [d.id for d in self.derived]),
            ("etapa", [s.id for s in self.steps]),
            ("método de atributos", [r.method for r in self.attribute_rules]),
        ):
            problems += [f"{label} duplicado: {d!r}" for d in _duplicates(ids)]

        for skill in self.skills:
            if skill.attribute is not None and skill.attribute not in attr_ids:
                problems.append(
                    f"perícia {skill.id!r} usa atributo inexistente {skill.attribute!r}"
                )
        if self.skill_min > self.skill_max:
            problems.append("skill_min maior que skill_max")

        for rule in self.attribute_rules:
            problems += self._rule_problems(rule)

        skill_ids = set(self.skill_ids())
        flag_groups = {d.flag_from for d in self.derived if d.flag_from is not None}
        for choice in self.choices:
            fields = numeric_fields(choice)
            for option in choice.options:
                where = f"opção {choice.id}.{option.id}"
                skill_refs = set(option.allowed_skills or []) | set(option.granted_skills)
                unknown_skills = sorted(skill_refs - skill_ids)
                if unknown_skills:
                    problems.append(f"{where}: perícias inexistentes {unknown_skills}")
                priorities = option.priority_attributes or []
                if set(priorities) - attr_ids or len(set(priorities)) != len(priorities):
                    problems.append(f"{where}: priority_attributes inválido {priorities}")
                for group, ids in option.grants.items():
                    if group in flag_groups and set(ids) - attr_ids:
                        problems.append(f"{where}: grants.{group} usa atributos inexistentes")
                for attr in option.attribute_bonuses:
                    if attr not in attr_ids:
                        problems.append(
                            f"opção {choice.id}.{option.id}: atributo inexistente {attr!r}"
                        )
                missing = fields - {k for k, v in option.data.items() if is_number(v)}
                if missing:
                    problems.append(
                        f"opção {choice.id}.{option.id}: faltam campos numéricos {sorted(missing)}"
                    )

        groups = {g for c in self.choices for o in c.options for g in o.grants}
        for d in self.derived:
            if d.flag_from is None:
                continue
            if not d.per_attribute:
                problems.append(f"derivado {d.id!r}: flag_from exige per_attribute")
            if d.flag_from not in groups:
                problems.append(f"derivado {d.id!r}: nenhuma opção concede {d.flag_from!r}")

        problems += self._formula_problems(attr_ids)
        problems += self._step_problems()
        return problems

    def _rule_problems(self, rule: AllocationRule) -> list[str]:
        out: list[str] = []
        label = f"método {rule.method}"
        if (
            rule.min_score is not None
            and rule.max_score is not None
            and (rule.min_score > rule.max_score)
        ):
            out.append(f"{label}: min_score maior que max_score")
        if rule.method == "point_buy":
            if rule.budget is None or rule.min_score is None or rule.max_score is None:
                out.append(f"{label}: exige budget, min_score e max_score")
            elif rule.min_score <= rule.max_score:
                missing = [
                    v for v in range(rule.min_score, rule.max_score + 1) if v not in rule.costs
                ]
                if missing:
                    out.append(f"{label}: faltam custos para os valores {missing}")
        if rule.method == "standard_array" and len(rule.array) != len(self.attributes):
            out.append(f"{label}: array deve ter {len(self.attributes)} valores")
        return out

    def _formula_problems(self, attr_ids: set[str]) -> list[str]:
        problems: list[str] = []
        available: set[str] = set(attr_ids)

        def declare(name: str) -> None:
            if name in available:
                problems.append(f"nome de variável duplicado: {name!r}")
            available.add(name)

        for choice in self.choices:
            for fld in sorted(numeric_fields(choice)):
                declare(f"{choice.id}_{fld}")

        per_attr_ids: list[str] = []  # derivados por atributo já declarados (usáveis sem prefixo)
        for d in self.derived:
            local = {"value", *per_attr_ids} if d.per_attribute else set()
            if d.per_attribute and d.flag_from is not None:
                local.add("granted")
            allowed = available | local
            try:
                unknown = formula_names(d.formula) - allowed
            except ExpressionError as exc:
                problems.append(f"derivado {d.id!r}: {exc}")
                unknown = set()
            if unknown:
                problems.append(f"derivado {d.id!r} usa variáveis desconhecidas {sorted(unknown)}")
            if d.per_attribute:
                for attr in self.attribute_ids():
                    declare(f"{attr}_{d.id}")
                per_attr_ids.append(d.id)
            else:
                declare(d.id)

        for label, formula, extra in (
            ("skill_budget", self.skill_budget, set[str]()),
            ("skill_modifier", self.skill_modifier, {"value", "proficient", *per_attr_ids}),
        ):
            if formula is None:
                continue
            try:
                unknown = formula_names(formula) - available - extra
            except ExpressionError as exc:
                problems.append(f"{label}: {exc}")
            else:
                if unknown:
                    problems.append(f"{label} usa variáveis desconhecidas {sorted(unknown)}")
        return problems

    def _step_problems(self) -> list[str]:
        problems: list[str] = []
        choice_ids = {c.id for c in self.choices}
        for step in self.steps:
            if step.kind == "choice" and step.target not in choice_ids:
                problems.append(f"etapa {step.id!r}: escolha inexistente {step.target!r}")
            if step.kind != "choice" and step.target is not None:
                problems.append(f"etapa {step.id!r}: 'target' só vale para kind=choice")
            if step.kind == "narrative" and step.fills is None:
                problems.append(f"etapa {step.id!r}: kind=narrative exige 'fills'")
            if step.kind != "narrative" and step.fills is not None:
                problems.append(f"etapa {step.id!r}: 'fills' só vale para kind=narrative")
            if step.kind == "skills" and not self.skills:
                problems.append(f"etapa {step.id!r}: o pack não define perícias")
        return problems
