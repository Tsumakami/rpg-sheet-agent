"""Aplica uma sugestão do StepAdvisor à ficha, sempre pelo SheetEditor."""

from rpg_agent.application.step_advisor import (
    AttributesSuggestion,
    ChoiceSuggestion,
    SkillsSuggestion,
    StepSuggestion,
)
from rpg_agent.domain.editor import EditResult, SheetEditor
from rpg_agent.domain.models.character import Character


def apply_suggestion(
    editor: SheetEditor, character: Character, suggestion: StepSuggestion
) -> EditResult:
    """Levanta RuleViolationError se a sugestão violar as regras (a ficha não muda)."""
    if isinstance(suggestion, ChoiceSuggestion):
        return editor.set_choice(character, suggestion.choice_id, suggestion.option_id)
    if isinstance(suggestion, AttributesSuggestion):
        return editor.set_attributes(character, suggestion.method, suggestion.scores)
    if isinstance(suggestion, SkillsSuggestion):
        skills = dict.fromkeys(suggestion.skill_ids, editor.pack.skill_max)
        return editor.set_skills(character, skills)
    return editor.set_text(character, suggestion.field, suggestion.suggestions[0])
