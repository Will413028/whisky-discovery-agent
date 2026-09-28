from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from whisky.modules.catalog.domain import Bottle, PriceObservation, price_upper_bound


def sample_quote():
    bottle = Bottle(uuid4(), Decimal("46"), 700)
    observation = PriceObservation(
        source_id=uuid4(),
        bottle=bottle,
        observed_at=datetime(2026, 9, 28, tzinfo=UTC),
        checked_on=date(2026, 9, 28),
        amount=Decimal("1500.50"),
        reviewed=True,
    )
    return bottle, observation


def test_reviewed_matching_taiwan_quote_has_an_exact_decimal_upper_bound():
    bottle, observation = sample_quote()
    assert price_upper_bound(bottle, [observation], date(2026, 9, 28)) == Decimal(
        "1500.50"
    )


def test_draft_price_cannot_qualify_for_a_budget():
    bottle, observation = sample_quote()
    assert (
        price_upper_bound(
            bottle, [replace(observation, reviewed=False)], date(2026, 9, 28)
        )
        is None
    )


@pytest.mark.parametrize(
    "difference", [{"version_id": uuid4()}, {"abv": Decimal("40")}, {"volume_ml": 1000}]
)
def test_different_bottle_cannot_supply_the_requested_bottles_price(difference):
    bottle, observation = sample_quote()
    observation = replace(observation, bottle=replace(bottle, **difference))
    assert price_upper_bound(bottle, [observation], date(2026, 9, 28)) is None


@pytest.mark.parametrize(
    "difference", [{"market": "US"}, {"currency": "USD"}, {"unconditional": False}]
)
def test_non_taiwan_or_conditional_quotes_do_not_qualify(difference):
    bottle, observation = sample_quote()
    assert (
        price_upper_bound(
            bottle, [replace(observation, **difference)], date(2026, 9, 28)
        )
        is None
    )


@pytest.mark.parametrize(
    "age,expected",
    [
        (0, Decimal("1500.50")),
        (30, Decimal("1500.50")),
        (31, None),
        (-1, None),
        (None, None),
    ],
)
def test_calendar_day_freshness_includes_day_30_but_rejects_missing_or_future_dates(
    age, expected
):
    bottle, observation = sample_quote()
    today = date(2026, 9, 28)
    checked_on = today - timedelta(days=age) if age is not None else None
    assert (
        price_upper_bound(bottle, [replace(observation, checked_on=checked_on)], today)
        == expected
    )


def test_latest_withdrawal_does_not_fall_back_to_a_sources_old_quote():
    bottle, quote = sample_quote()
    withdrawn = replace(
        quote, observed_at=quote.observed_at + timedelta(hours=1), amount=None
    )
    assert price_upper_bound(bottle, [withdrawn, quote], date(2026, 9, 28)) is None


def test_each_sources_latest_quote_is_selected_before_taking_the_upper_bound():
    bottle, quote = sample_quote()
    newer = replace(
        quote,
        observed_at=quote.observed_at + timedelta(hours=1),
        amount=Decimal("1200"),
    )
    other_source = replace(quote, source_id=uuid4(), amount=Decimal("1300"))
    assert price_upper_bound(
        bottle, [newer, other_source, quote], date(2026, 9, 28)
    ) == Decimal("1300")
