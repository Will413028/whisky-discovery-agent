"""Pure catalog rules; no database, agent or transport dependencies."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class Bottle:
    version_id: UUID
    abv: Decimal
    volume_ml: int


@dataclass(frozen=True)
class PriceObservation:
    source_id: UUID
    bottle: Bottle
    observed_at: datetime
    checked_on: date | None
    amount: Decimal | None
    reviewed: bool
    market: str = "TW"
    currency: str = "TWD"
    unconditional: bool = True


@dataclass(frozen=True)
class PricePolicy:
    maximum_age_days: int = 30


def price_upper_bound(
    bottle: Bottle,
    observations: list[PriceObservation],
    as_of: date,
    policy: PricePolicy = PricePolicy(),
) -> Decimal | None:
    latest: dict[UUID, PriceObservation] = {}
    for observation in observations:
        if observation.bottle != bottle:
            continue
        previous = latest.get(observation.source_id)
        if previous is None or observation.observed_at > previous.observed_at:
            latest[observation.source_id] = observation
    return max(
        (
            observation.amount
            for observation in latest.values()
            if observation.bottle == bottle
            and observation.reviewed
            and observation.amount is not None
            and observation.market == "TW"
            and observation.currency == "TWD"
            and observation.unconditional
            and observation.checked_on is not None
            and 0 <= (as_of - observation.checked_on).days <= policy.maximum_age_days
        ),
        default=None,
    )
