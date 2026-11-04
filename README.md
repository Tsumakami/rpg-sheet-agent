# rpg-sheet-agent

Agente de IA local para criar fichas de RPG de mesa (D&D 5e, Vampiro e outros), via Ollama.

## Setup rápido

1. Instale o [Ollama](https://ollama.com) e baixe o modelo: `ollama pull llama3.2:3b`
2. Instale o [uv](https://docs.astral.sh/uv/getting-started/installation/)
3. Na pasta do projeto:

```
cp .env.example .env
git init
uv sync
uv run pre-commit install
uv run rpg-agent doctor
uv run pytest -m "not llm"
```

Comandos úteis: `make check` (lint + tipos + testes), `make doctor`.
