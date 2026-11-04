"""CLI do agente."""

import time
from typing import Any

import ollama
import typer
from pydantic import BaseModel

from rpg_agent.adapters.llm.ollama import OllamaAdapter
from rpg_agent.adapters.rules.yaml_loader import YamlRulePackLoader
from rpg_agent.config import get_settings
from rpg_agent.domain.errors import RulePackError

app = typer.Typer(help="Agente criador de fichas de RPG.", no_args_is_help=True)


class _Ping(BaseModel):
    ok: bool


def _model_names(listing: Any) -> list[str]:
    """Compatível com versões diferentes do cliente (dict ou objeto)."""
    models = listing["models"] if isinstance(listing, dict) else listing.models
    names: list[str] = []
    for m in models:
        name = (m.get("model") or m.get("name")) if isinstance(m, dict) else m.model
        if name:
            names.append(str(name))
    return names


@app.callback()
def main() -> None:
    """Agente criador de fichas de RPG."""


@app.command()
def doctor() -> None:
    """Verifica se o Ollama e o modelo configurado estão funcionando."""
    settings = get_settings()
    typer.echo(f"Host:   {settings.ollama_host}")
    typer.echo(f"Modelo: {settings.model} (num_ctx={settings.num_ctx})")

    try:
        names = _model_names(ollama.Client(host=settings.ollama_host).list())
    except Exception as exc:
        typer.secho(f"[FALHA] Não consegui falar com o Ollama: {exc}", fg=typer.colors.RED)
        typer.echo("Dica: instale o Ollama e rode `ollama serve` (ou abra o app).")
        raise typer.Exit(code=1) from exc
    typer.secho("[OK] Ollama respondeu.", fg=typer.colors.GREEN)

    if not any(n == settings.model or n.startswith(f"{settings.model}:") for n in names):
        typer.secho(
            f"[FALHA] Modelo ausente. Rode: ollama pull {settings.model}", fg=typer.colors.RED
        )
        raise typer.Exit(code=1)
    typer.secho("[OK] Modelo instalado.", fg=typer.colors.GREEN)

    start = time.perf_counter()
    raw = OllamaAdapter(settings).generate_structured(
        system="Responda apenas com JSON.",
        user='Responda {"ok": true}.',
        json_schema=_Ping.model_json_schema(),
    )
    elapsed = time.perf_counter() - start
    _Ping.model_validate_json(raw)
    typer.secho(
        f"[OK] Saída estruturada válida em {elapsed:.1f}s (a 1ª chamada inclui o carregamento).",
        fg=typer.colors.GREEN,
    )
    typer.echo("Dica: rode `ollama ps` e confirme que o modelo está em 100% GPU.")


@app.command()
def packs() -> None:
    """Lista e valida todos os Rule Packs (sistemas de RPG) disponíveis."""
    settings = get_settings()
    loader = YamlRulePackLoader(settings.rule_packs_dir)
    systems = loader.list_systems()
    if not systems:
        typer.secho(f"Nenhum Rule Pack em {settings.rule_packs_dir}", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    failed = False
    for system_id in systems:
        try:
            pack = loader.load(system_id)
        except RulePackError as exc:
            failed = True
            typer.secho(f"[FALHA] {system_id}", fg=typer.colors.RED)
            typer.echo(str(exc))
        else:
            typer.secho(
                f"[OK] {system_id}: {pack.name} v{pack.version} - "
                f"{len(pack.attributes)} atributos, {len(pack.skills)} perícias, "
                f"{len(pack.choices)} escolhas, {len(pack.steps)} etapas",
                fg=typer.colors.GREEN,
            )
    if failed:
        raise typer.Exit(code=1)
