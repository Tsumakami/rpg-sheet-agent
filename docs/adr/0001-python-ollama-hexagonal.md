# ADR-0004: SheetEditor como único ponto de alteração da ficha

**Status:** Accepted

## Contexto
Validar a ficha só no final deixa o sistema aceitar estados inválidos no meio da criação,
e uma alteração posterior (ex.: trocar de classe depois de escolher perícias) pode quebrar
etapas já concluídas sem ninguém perceber.

## Decisão
- Toda alteração passa por `SheetEditor` (`set_choice`, `set_attributes`, `set_skills`,
  `set_text`). Cada chamada devolve uma ficha NOVA; a original nunca é modificada.
- A alteração só é aceita se o resultado passar na validação do Rule Pack; senão,
  `RuleViolationError` com os problemas, e a ficha original continua intacta.
- Se a alteração invalidar OUTRAS etapas já concluídas, elas são reabertas (dados limpos)
  e o resultado informa quais (`reopened_steps`), em vez de deixar a ficha inconsistente.
- `finalize` só aprova a ficha completa e válida (`require_complete=True`).
- As sugestões do LLM entram pelo mesmo caminho (`apply_suggestion`): o que o modelo
  sugere nunca chega à ficha sem passar pelas regras.
- Restrições de lista vêm do pack (`allowed_skills`) e são aplicadas em três lugares:
  schema do LLM, validador e editor.

## Limites conhecidos (D&D 5e SRD, fase atual)
Ainda não modelados no pack: perícias do antecedente, salvaguardas por classe, equipamento,
idiomas, magias e níveis acima do 1. O que está modelado é imposto pelas regras.
