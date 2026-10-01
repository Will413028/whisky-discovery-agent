"""Closed record shape for versioned downloadable product data."""

from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict


@dataclass(frozen=True)
class ExportRelation:
    """Trusted module-owned SQL projection, never accepted from an HTTP input."""

    sql: str
    owner: UUID
    generation: int

    @property
    def parameters(self) -> dict[str, UUID | int]:
        return dict(owner=self.owner, generation=self.generation)


class ExportRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
