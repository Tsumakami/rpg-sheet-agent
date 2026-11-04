# Como criar um Rule Pack

Crie `rule_packs/<id>/` (id em minúsculas, `a-z0-9_`) com `system.yaml` (obrigatório) e, se quiser,
`choices.yaml`, `skills.yaml`, `steps.yaml`. Valide com `uv run rpg-agent packs`.

| Chave | Descrição |
|---|---|
| `schema_version`, `id`, `name`, `version` | Metadados. `id` deve ser igual ao nome da pasta. |
| `license`, `attribution` | Obrigatório respeitar a licença do conteúdo (ex.: CC-BY do SRD). |
| `attributes` | Lista de `{id, name}`. |
| `attribute_rules` | Métodos permitidos: `point_buy`, `standard_array`, `roll`, `free`. |
| `skills`, `skill_min`, `skill_max`, `skill_budget` | Perícias, intervalo de valores e limite total (fórmula). |
| `choices` | Escolhas categóricas (raça, classe, clã...) com `options`. |
| `choices[].options[].allowed_skills` | Perícias que a opção libera (ex.: lista da classe). Sem o campo, qualquer perícia vale. |
| `derived` | Valores calculados por fórmula. `per_attribute: true` gera `<atributo>_<id>`. |
| `steps` | Etapas da criação: `narrative` (com `fills`), `choice` (com `target`), `attributes`, `skills`. |

**Fórmulas** aceitam números, variáveis, `+ - * / // %`, parênteses e `floor ceil min max abs`.
Variáveis disponíveis: ids de atributos, derivados anteriores e `<escolha>_<campo>` numéricos.

**Direitos autorais:** inclua só conteúdo que você tem direito de usar. O pack `dnd5e_srd`
usa apenas material do SRD 5.1 (CC-BY-4.0).
