"""Erros de domínio."""


class RulePackError(Exception):
    """Rule Pack inválido, malformado ou impossível de carregar."""


class RulePackNotFoundError(RulePackError):
    """Rule Pack solicitado não existe."""
