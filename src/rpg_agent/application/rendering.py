"""Renderização dos prompts (templates Jinja2 versionados em `templates/`)."""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


class PromptRenderer:
    def __init__(self, templates_dir: Path = TEMPLATES_DIR) -> None:
        self._env = Environment(
            loader=FileSystemLoader(templates_dir),
            undefined=StrictUndefined,  # variável faltando vira erro, não prompt errado
            trim_blocks=True,
            lstrip_blocks=True,
            autoescape=False,  # texto puro para o LLM, não HTML
        )

    def render(self, template: str, **context: Any) -> str:
        return self._env.get_template(template).render(**context).strip()
