"""Common JSON type aliases and model base class."""

from typing import TypeAlias

from pydantic import BaseModel, ConfigDict

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list[object] | dict[str, object]


class OpenMappingModel(BaseModel):
    """Frozen Pydantic base that rejects unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")
