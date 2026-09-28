"""Explicit reviewed-manifest import boundary; never promotes draft content."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from whisky.modules.catalog.domain import CatalogRelease, validate_release


class ReviewedManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal[1]
    data_kind: Literal["real"]
    review_status: Literal["reviewed"]
    reviewed_by: str = Field(min_length=1)
    reviewed_at: datetime
    release: CatalogRelease


def load_reviewed_release(payload: str) -> CatalogRelease:
    document = ReviewedManifest.model_validate_json(payload)
    if (
        document.reviewed_at.utcoffset() is None
        or document.release.published_at.utcoffset() is None
        or document.reviewed_at > document.release.published_at
    ):
        raise ValueError("An aware human review must precede publication")
    validate_release(document.release)
    return document.release
