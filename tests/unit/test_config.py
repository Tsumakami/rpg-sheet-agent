import pytest

from rpg_agent.config import Settings


def test_defaults_fit_small_gpu() -> None:
    s = Settings()
    assert s.model == "llama3.2:3b"
    assert s.num_ctx <= 4096


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RPG_MODEL", "qwen2.5:3b")
    assert Settings().model == "qwen2.5:3b"
