"""Configuração da aplicação via variáveis de ambiente (prefixo RPG_)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RPG_", env_file=".env", extra="ignore")

    ollama_host: str = "http://localhost:11434"
    model: str = "llama3.2:3b"
    # 4096 mantém o KV cache pequeno o bastante para caber em 4 GB de VRAM.
    num_ctx: int = 4096
    temperature: float = 0.4
    timeout_s: float = 120.0
    max_retries: int = 2
    rule_packs_dir: Path = Path("rule_packs")


def get_settings() -> Settings:
    return Settings()
