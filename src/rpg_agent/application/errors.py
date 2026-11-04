"""Erros da camada de aplicação."""

from collections.abc import Sequence

from rpg_agent.ports.llm import LLMError


class LLMOutputError(LLMError):
    """O modelo não produziu uma saída válida dentro do limite de tentativas."""

    def __init__(self, problems_by_attempt: Sequence[Sequence[str]]) -> None:
        self.problems_by_attempt = [list(p) for p in problems_by_attempt]
        last = "; ".join(self.problems_by_attempt[-1]) if self.problems_by_attempt else "?"
        super().__init__(
            f"Saída inválida do modelo após {len(self.problems_by_attempt)} tentativa(s). "
            f"Último problema: {last}"
        )


class StepPreconditionError(ValueError):
    """A etapa não pode ser sugerida agora (ex.: perícias antes de escolher a classe)."""


class ChoiceNotFoundError(ValueError):
    """O texto do jogador não casou com nenhuma opção (ou casou com mais de uma)."""

    def __init__(self, text: str, candidates: Sequence[str]) -> None:
        self.text = text
        self.candidates = list(candidates)
        super().__init__(
            f"{text!r} não corresponde a uma opção única. Opções: {', '.join(candidates)}."
        )
