from pydantic import BaseModel, ConfigDict, Field, JsonValue


class Character(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    system_id: str = Field(min_length=1)
    name: str = ""
    concept: str = ""
    background: str = ""

    # atributos-base, por id (ex.: {"str": 15, "dex": 14})
    attributes: dict[str, int] = Field(default_factory=dict)
    # método usado para distribuir os atributos (point_buy, standard_array, roll...)
    attribute_method: str | None = None
    # perícias por id, com o nível/pontos (D&D: 0 ou 1; Vampiro: 0 a 5)
    skills: dict[str, int] = Field(default_factory=dict)
    # escolhas categóricas: {"race": "elf", "class": "wizard", "clan": "toreador"}
    choices: dict[str, str] = Field(default_factory=dict)

    traits: list[str] = Field(default_factory=list)
    inventory: list[str] = Field(default_factory=list)
    # espaço para dados específicos de um sistema (ex.: Disciplinas em Vampiro)
    extras: dict[str, JsonValue] = Field(default_factory=dict)

    # etapas da criação já concluídas (ids definidos no Rule Pack)
    completed_steps: list[str] = Field(default_factory=list)
