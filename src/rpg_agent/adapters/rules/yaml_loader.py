"""Carrega Rule Packs de uma pasta: rule_packs/<id>/*.yaml.

Todos os arquivos .yaml da pasta são mesclados (chaves de topo não podem se repetir),
o que permite separar o pack em system.yaml, choices.yaml, skills.yaml, steps.yaml etc.
Usa `yaml.safe_load`; nenhum código do pack é executado.
"""

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from rpg_agent.domain.errors import RulePackError, RulePackNotFoundError
from rpg_agent.domain.rule_system import RulePack

_SYSTEM_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_ENTRY_FILE = "system.yaml"


class YamlRulePackLoader:
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def list_systems(self) -> list[str]:
        if not self._base_dir.is_dir():
            return []
        return sorted(
            p.name
            for p in self._base_dir.iterdir()
            if p.is_dir() and _SYSTEM_ID.match(p.name) and (p / _ENTRY_FILE).is_file()
        )

    def load_raw(self, system_id: str) -> dict[str, Any]:
        if not _SYSTEM_ID.match(system_id):
            raise RulePackError(f"id de sistema inválido: {system_id!r}")
        pack_dir = self._base_dir / system_id
        if not (pack_dir / _ENTRY_FILE).is_file():
            raise RulePackNotFoundError(
                f"Rule Pack não encontrado: {system_id!r} em {self._base_dir}"
            )

        merged: dict[str, Any] = {}
        for file in sorted(pack_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                raise RulePackError(f"YAML inválido em {file.name}: {exc}") from exc
            if not isinstance(data, dict):
                raise RulePackError(f"{file.name}: o conteúdo deve ser um mapa (chave: valor)")
            duplicated = sorted(merged.keys() & data.keys())
            if duplicated:
                raise RulePackError(
                    f"{file.name}: chaves já definidas em outro arquivo: {duplicated}"
                )
            merged.update(data)
        return merged

    def load(self, system_id: str) -> RulePack:
        raw = self.load_raw(system_id)
        if raw.get("id") != system_id:
            raise RulePackError(
                f"id do pack ({raw.get('id')!r}) difere do nome da pasta ({system_id!r})"
            )
        try:
            return RulePack.model_validate(raw)
        except ValidationError as exc:
            raise RulePackError(f"Rule Pack {system_id!r} inválido:\n{exc}") from exc
