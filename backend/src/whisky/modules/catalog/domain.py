"""Pure catalog rules; no database, agent or transport dependencies."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from ipaddress import ip_address
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Bottle:
    version_id: UUID
    abv: Decimal | None
    volume_ml: int | None

    def __post_init__(self) -> None:
        if self.abv is not None and (
            not self.abv.is_finite() or not 0 < self.abv <= 100
        ):
            raise ValueError("ABV must be finite and in (0, 100]")
        if self.volume_ml is not None and self.volume_ml <= 0:
            raise ValueError("Bottle volume must be positive")


@dataclass(frozen=True)
class PriceObservation:
    source_id: UUID
    bottle: Bottle
    observed_at: datetime
    checked_on: date | None
    amount: Decimal | None
    reviewed: bool
    market: str
    currency: str
    unconditional: bool

    def __post_init__(self) -> None:
        if self.observed_at.utcoffset() is None:
            raise ValueError("Observation capture time must be timezone-aware")
        if self.amount is not None and (
            not self.amount.is_finite() or self.amount <= 0
        ):
            raise ValueError("A quoted price must be finite and positive")


@dataclass(frozen=True)
class PricePolicy:
    maximum_age_days: int = 30


@dataclass(frozen=True)
class Evidence:
    id: UUID
    source_id: UUID
    bottle_version_id: UUID
    url: str
    captured_at: datetime
    checked_on: date
    reviewed: bool


@dataclass(frozen=True)
class CatalogFact:
    field: str
    value: str
    evidence_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class FlavorTag:
    label: str
    evidence_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class CatalogItem:
    id: UUID
    bottle: Bottle
    name: str
    facts: tuple[CatalogFact, ...]
    flavor_tags: tuple[FlavorTag, ...]
    reviewed: bool


@dataclass(frozen=True)
class PublishedPrice:
    id: UUID
    item_id: UUID
    evidence_id: UUID
    observation: PriceObservation


@dataclass(frozen=True)
class CatalogRelease:
    id: UUID
    published_at: datetime
    items: tuple[CatalogItem, ...]
    evidence: tuple[Evidence, ...]
    prices: tuple[PublishedPrice, ...] = ()


def validate_release(release: CatalogRelease) -> None:
    published_on = taiwan_date(release.published_at)
    if len({item.id for item in release.items}) != len(release.items):
        raise ValueError("Duplicate item identifiers")
    if len({evidence.id for evidence in release.evidence}) != len(release.evidence):
        raise ValueError("Duplicate evidence identifiers")
    for evidence in release.evidence:
        url = urlsplit(evidence.url)
        # Accessing port validates its syntax and range; no network lookup occurs.
        _ = url.port
        hostname = (url.hostname or "").rstrip(".").lower()
        try:
            public_host = ip_address(hostname).is_global
        except ValueError:
            public_host = "." in hostname and not hostname.endswith(
                (".localhost", ".local", ".internal")
            )
        if (
            url.scheme not in {"http", "https"}
            or not public_host
            or url.username
            or url.password
        ):
            raise ValueError("Evidence requires a public HTTP URL without credentials")
        if (
            evidence.captured_at.utcoffset() is None
            or evidence.captured_at > release.published_at
        ):
            raise ValueError(
                "Evidence capture must be aware and no later than publication"
            )
        if evidence.checked_on > published_on:
            raise ValueError("Evidence check date cannot be in the future")
    if any(not item.reviewed for item in release.items):
        raise ValueError("Only reviewed items can be published")
    evidence_by_id = {evidence.id: evidence for evidence in release.evidence}
    items_by_id = {item.id: item for item in release.items}
    if len({price.id for price in release.prices}) != len(release.prices):
        raise ValueError("Duplicate price identifiers")
    for price in release.prices:
        item = items_by_id.get(price.item_id)
        source = evidence_by_id.get(price.evidence_id)
        observation = price.observation
        if (
            item is None
            or source is None
            or not source.reviewed
            or not observation.reviewed
            or observation.bottle != item.bottle
            or source.bottle_version_id != item.bottle.version_id
            or observation.source_id != source.source_id
            or observation.observed_at != source.captured_at
            or (
                observation.checked_on is not None
                and observation.checked_on != source.checked_on
            )
        ):
            raise ValueError("Price must cite reviewed same-source bottle evidence")
    for item in release.items:
        facts = {fact.field: fact for fact in item.facts}
        if len(facts) != len(item.facts):
            raise ValueError("Duplicate fact fields")
        expected = {"name": item.name}
        if item.bottle.abv is not None:
            try:
                sourced_abv = Decimal(facts["abv"].value)
            except (KeyError, InvalidOperation) as error:
                raise ValueError(
                    "Display fields must match their sourced facts"
                ) from error
            if not sourced_abv.is_finite() or sourced_abv != item.bottle.abv:
                raise ValueError("Display fields must match their sourced facts")
        if item.bottle.volume_ml is not None:
            expected["volume_ml"] = str(item.bottle.volume_ml)
        for field, value in expected.items():
            if field not in facts or facts[field].value != value:
                raise ValueError("Display fields must match their sourced facts")
        claims: tuple[CatalogFact | FlavorTag, ...] = (*item.facts, *item.flavor_tags)
        for claim in claims:
            if not claim.evidence_ids:
                raise ValueError("Every fact and derived tag requires evidence")
            for identifier in claim.evidence_ids:
                cited = evidence_by_id.get(identifier)
                if (
                    cited is None
                    or not cited.reviewed
                    or cited.bottle_version_id != item.bottle.version_id
                ):
                    raise ValueError(
                        "Citation must resolve to reviewed same-bottle evidence"
                    )


def taiwan_date(instant: datetime) -> date:
    if instant.utcoffset() is None:
        raise ValueError("An aware timestamp is required")
    return instant.astimezone(ZoneInfo("Asia/Taipei")).date()


def fits_budget(upper_bound: Decimal | None, budget: Decimal | None) -> bool:
    return budget is None or (upper_bound is not None and upper_bound <= budget)


def qualified_prices(
    bottle: Bottle,
    observations: list[PriceObservation],
    as_of: date,
    policy: PricePolicy = PricePolicy(),
) -> tuple[PriceObservation, ...]:
    if bottle.abv is None or bottle.volume_ml is None:
        return ()
    latest: dict[UUID, PriceObservation] = {}
    ambiguous: set[UUID] = set()
    for observation in observations:
        if observation.bottle != bottle:
            continue
        previous = latest.get(observation.source_id)
        if previous is None or observation.observed_at > previous.observed_at:
            latest[observation.source_id] = observation
            ambiguous.discard(observation.source_id)
        elif (
            observation.observed_at == previous.observed_at and observation != previous
        ):
            ambiguous.add(observation.source_id)
    return tuple(
        observation
        for observation in latest.values()
        if observation.bottle == bottle
        and observation.source_id not in ambiguous
        and observation.reviewed
        and observation.amount is not None
        and observation.market == "TW"
        and observation.currency == "TWD"
        and observation.unconditional
        and observation.checked_on is not None
        and 0 <= (as_of - observation.checked_on).days <= policy.maximum_age_days
    )


def price_upper_bound(
    bottle: Bottle,
    observations: list[PriceObservation],
    as_of: date,
    policy: PricePolicy = PricePolicy(),
) -> Decimal | None:
    return max(
        (
            quote.amount
            for quote in qualified_prices(bottle, observations, as_of, policy)
            if quote.amount is not None
        ),
        default=None,
    )


@dataclass(frozen=True)
class CatalogCandidate:
    release_id: UUID
    item: CatalogItem
    prices: tuple[PublishedPrice, ...]

    @property
    def price_upper_bound(self) -> Decimal | None:
        return max(
            (
                price.observation.amount
                for price in self.prices
                if price.observation.amount is not None
            ),
            default=None,
        )
