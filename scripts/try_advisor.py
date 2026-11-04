"""Teste manual do StepAdvisor + SheetEditor com o Ollama real.

Uso:  uv run python scripts/try_advisor.py "um mago élfico sombrio"
"""

import sys

from rpg_agent.adapters.llm.ollama import OllamaAdapter
from rpg_agent.adapters.rules.yaml_loader import YamlRulePackLoader
from rpg_agent.application.apply import apply_suggestion
from rpg_agent.application.errors import LLMOutputError
from rpg_agent.application.step_advisor import StepAdvisor
from rpg_agent.config import get_settings
from rpg_agent.domain.editor import RuleViolationError, SheetEditor
from rpg_agent.domain.engine import compute_sheet
from rpg_agent.domain.models.character import Character


def main() -> None:
    concept = " ".join(sys.argv[1:]) or "um mago élfico sombrio e estudioso"
    settings = get_settings()
    pack = YamlRulePackLoader(settings.rule_packs_dir).load("dnd5e_srd")
    advisor = StepAdvisor(OllamaAdapter(settings), max_retries=settings.max_retries)
    editor = SheetEditor(pack)
    character = Character(system_id=pack.id, concept=concept, attribute_method="standard_array")

    print(f"Modelo: {settings.model} | conceito: {concept}\n")
    for step in pack.steps:
        if step.id == "concept":
            continue
        try:
            suggestion = advisor.suggest(pack, character, step.id, user_input=concept)
            result = apply_suggestion(editor, character, suggestion)
        except LLMOutputError as exc:
            print(f"[{step.title}] o modelo não produziu saída válida: {exc}")
            continue
        except RuleViolationError as exc:
            print(f"[{step.title}] sugestão recusada pelas regras: {exc}")
            continue

        character = result.character
        r = suggestion.report
        print(f"[{step.title}] tentativas={r.attempts} tempo={r.latency_s:.1f}s ok")
        if result.reopened_steps:
            print(f"  (etapas reabertas: {list(result.reopened_steps)})")

    print("\n=== Ficha ===")
    print(character.model_dump_json(indent=2, exclude_defaults=True))
    sheet = compute_sheet(pack, character)
    print("Derivados:", sheet.derived)
    saves = {
        a: sheet.derived[f"{a}_save"] for a in pack.attribute_ids() if f"{a}_save" in sheet.derived
    }
    print("Salvaguardas:", saves)
    skills = {
        s: sheet.skill_modifiers[s] for s in sheet.proficient_skills if s in sheet.skill_modifiers
    }
    print("Perícias proficientes:", skills)
    try:
        editor.finalize(character)
        print("\nFicha COMPLETA e válida segundo as regras do sistema.")
    except RuleViolationError as exc:
        print(f"\nFicha incompleta ou inválida: {exc}")


if __name__ == "__main__":
    main()
