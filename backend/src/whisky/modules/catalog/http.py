"""Anonymous projections of sealed reviewed catalog data."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import Engine

from whisky.modules.catalog import public
from whisky.modules.catalog.store import CatalogStore
from whisky.platform.http_errors import PublicAPIError


class CatalogViewModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CatalogSourceView(CatalogViewModel):
    evidence_id: UUID
    url: str = Field(pattern=r"^https?://")
    publisher: str | None
    checked_on: date


class CatalogClaimView(CatalogViewModel):
    kind: Literal["fact", "tag"]
    key: str
    value: str
    sources: tuple[CatalogSourceView, ...]


class CatalogFlavorView(CatalogViewModel):
    label: str
    evidence_ids: tuple[UUID, ...]
    method: str | None
    method_version: str | None


class CatalogPriceView(CatalogViewModel):
    id: UUID
    amount: Decimal | None
    currency: str
    market: str
    volume_ml: int | None
    checked_on: date | None
    unconditional: bool
    qualified: bool
    source: CatalogSourceView


class CatalogItemView(CatalogViewModel):
    item_id: UUID
    bottle_version_id: UUID
    name: str
    version_label: str
    abv: Decimal | None
    volume_ml: int | None
    claims: tuple[CatalogClaimView, ...]
    flavor_tags: tuple[CatalogFlavorView, ...]
    prices: tuple[CatalogPriceView, ...]
    price_upper_bound_twd: Decimal | None
    price_qualification: Literal["qualified", "unqualified"]


class CatalogView(CatalogViewModel):
    release_id: UUID | None
    evaluated_on: date
    price_policy_version: str
    items: tuple[CatalogItemView, ...]


def catalog_router(engine: Engine | None) -> APIRouter:
    routes = APIRouter(prefix="/api/v1")

    @routes.get("/catalog", response_model=CatalogView)
    def read_catalog() -> CatalogView:
        if engine is None:
            raise PublicAPIError(503, "CATALOG_UNAVAILABLE")
        evaluated_on = public.taiwan_date(datetime.now(UTC))
        snapshot = public.reviewed_catalog_snapshot(engine, evaluated_on, None)
        store = CatalogStore(engine)
        items = []
        for candidate in snapshot.candidates:
            item = candidate.item

            def source_view(evidence_id: UUID) -> CatalogSourceView:
                evidence = store.evidence(candidate.release_id, evidence_id)
                if evidence is None:
                    raise PublicAPIError(503, "CATALOG_UNAVAILABLE")
                return CatalogSourceView(
                    evidence_id=evidence.id,
                    url=evidence.url,
                    publisher=evidence.publisher,
                    checked_on=evidence.checked_on,
                )

            claims = tuple(
                CatalogClaimView(
                    kind="fact",
                    key=fact.field,
                    value=fact.value,
                    sources=tuple(
                        source_view(identifier) for identifier in fact.evidence_ids
                    ),
                )
                for fact in item.facts
            ) + tuple(
                CatalogClaimView(
                    kind="tag",
                    key=tag.label,
                    value=tag.label,
                    sources=tuple(
                        source_view(identifier) for identifier in tag.evidence_ids
                    ),
                )
                for tag in item.flavor_tags
            )
            qualified_ids = {price.id for price in candidate.prices}
            prices = tuple(
                CatalogPriceView(
                    id=price.id,
                    amount=price.observation.amount,
                    currency=price.observation.currency,
                    market=price.observation.market,
                    volume_ml=price.observation.bottle.volume_ml,
                    checked_on=price.observation.checked_on,
                    unconditional=price.observation.unconditional,
                    qualified=price.id in qualified_ids,
                    source=source_view(price.evidence_id),
                )
                for price in store.prices(candidate.release_id, item.id)
            )
            items.append(
                CatalogItemView(
                    item_id=item.id,
                    bottle_version_id=item.bottle.version_id,
                    name=item.name,
                    version_label=next(
                        fact.value
                        for fact in item.facts
                        if fact.field == "version_label"
                    ),
                    abv=item.bottle.abv,
                    volume_ml=item.bottle.volume_ml,
                    claims=claims,
                    flavor_tags=tuple(
                        CatalogFlavorView(
                            label=tag.label,
                            evidence_ids=tag.evidence_ids,
                            method=tag.method,
                            method_version=tag.method_version,
                        )
                        for tag in item.flavor_tags
                    ),
                    prices=prices,
                    price_upper_bound_twd=candidate.price_upper_bound,
                    price_qualification="qualified"
                    if candidate.price_upper_bound is not None
                    else "unqualified",
                )
            )
        return CatalogView(
            release_id=snapshot.release_id,
            evaluated_on=evaluated_on,
            price_policy_version=public.price_policy_version(),
            items=tuple(items),
        )

    return routes
