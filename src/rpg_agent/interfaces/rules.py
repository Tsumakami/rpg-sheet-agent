"""Porta de acesso aos Rule Packs."""

from typing import Protocol

from rpg_agent.domain.rule_system import RulePack


class RuleRepositoryPort(Protocol):
    def list_systems(self) -> list[str]: ...

    def load(self, system_id: str) -> RulePack: ...
