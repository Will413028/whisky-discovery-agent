"""Closed record shape for versioned downloadable product data."""

from pydantic import BaseModel, ConfigDict


class ExportRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
