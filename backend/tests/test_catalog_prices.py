from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from whisky.modules.catalog.domain import (
    Bottle,
    PriceObservation,
    fits_budget,
    price_upper_bound,
    taiwan_date,
)


def sample_quote():
    bottle = Bottle(uuid4(), Decimal("46"), 700)
    observation = PriceObservation(
        source_id=uuid4(),
        bottle=bottle,
        observed_at=datetime(2026, 9, 28, tzinfo=UTC),
        checked_on=date(2026, 9, 28),
        amount=Decimal("1500.50"),
        reviewed=True,
        market="TW",
        currency="TWD",
        unconditional=True,
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


@pytest.mark.parametrize(
    "price,budget,expected",
    [
        (Decimal("1500"), Decimal("1500"), True),
        (Decimal("1500"), Decimal("1499"), False),
        (None, Decimal("1500"), False),
        (None, None, True),
    ],
)
def test_budget_equality_and_explicitly_disabled_price_filter(price, budget, expected):
    assert fits_budget(price, budget) is expected


def test_price_calendar_rolls_over_at_taiwan_midnight():
    assert taiwan_date(datetime(2026, 9, 28, 15, 59, 59, tzinfo=UTC)) == date(
        2026, 9, 28
    )
    assert taiwan_date(datetime(2026, 9, 28, 16, tzinfo=UTC)) == date(2026, 9, 29)


def test_naive_time_cannot_silently_choose_the_hosts_timezone():
    with pytest.raises(ValueError):
        taiwan_date(datetime(2026, 9, 28, 16))


@pytest.mark.parametrize(
    "amount", [Decimal("NaN"), Decimal("Infinity"), Decimal("-1"), Decimal("0")]
)
def test_invalid_prices_cannot_enter_the_domain(amount):
    _, observation = sample_quote()
    with pytest.raises(ValueError):
        replace(observation, amount=amount)


def test_observations_require_an_aware_capture_time():
    _, observation = sample_quote()
    with pytest.raises(ValueError):
        replace(observation, observed_at=datetime(2026, 9, 28))


@pytest.mark.parametrize("missing", [{"abv": None}, {"volume_ml": None}])
def test_unknown_bottle_attributes_never_count_as_a_comparable_price(missing):
    bottle, observation = sample_quote()
    unknown = replace(bottle, **missing)
    assert (
        price_upper_bound(
            unknown, [replace(observation, bottle=unknown)], date(2026, 9, 28)
        )
        is None
    )


@pytest.mark.parametrize(
    "invalid",
    [
        {"abv": Decimal("NaN")},
        {"abv": Decimal("0")},
        {"abv": Decimal("101")},
        {"volume_ml": 0},
    ],
)
def test_invalid_bottle_measurements_are_rejected(invalid):
    bottle, _ = sample_quote()
    with pytest.raises(ValueError):
        replace(bottle, **invalid)


@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_latest_observations_are_unknown_regardless_of_input_order(reverse):
    bottle, quote = sample_quote()
    conflict = replace(quote, amount=Decimal("1200"))
    observations = [quote, conflict]
    if reverse:
        observations.reverse()
    assert price_upper_bound(bottle, observations, date(2026, 9, 28)) is None


def test_a_later_observation_resolves_an_earlier_timestamp_conflict():
    bottle, quote = sample_quote()
    conflict = replace(quote, amount=Decimal("1200"))
    newer = replace(
        quote,
        observed_at=quote.observed_at + timedelta(hours=1),
        amount=Decimal("1300"),
    )
    assert price_upper_bound(
        bottle, [quote, conflict, newer], date(2026, 9, 28)
    ) == Decimal("1300")
