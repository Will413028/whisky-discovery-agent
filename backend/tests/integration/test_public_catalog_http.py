"""Visitors can inspect reviewed versions without accessing private records."""

from datetime import date
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from whisky.bootstrap.api import configured_app, create_app
from whisky.bootstrap.settings import Settings
from whisky.modules.catalog.publication import load_reviewed_release
from whisky.modules.catalog.store import CatalogStore

pytestmark = pytest.mark.integration


async def test_visitor_catalog_preserves_versions_sources_and_price_qualification(
    research_context, monkeypatch
):
    engine, _, _, _ = research_context
    release = load_reviewed_release(
        (
            Path(__file__).parents[3] / "data/catalog/first-journey.reviewed.json"
        ).read_text()
    )
    CatalogStore(engine).publish(release)
    monkeypatch.setattr(
        "whisky.modules.catalog.public.taiwan_date", lambda _: date(2026, 9, 30)
    )
    app = configured_app(
        Settings(
            str(engine.url),
            "https://whisky-fixture.example/",
            "https://whisky-api.example",
        )
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://test") as client,
    ):
        response = await client.get("/api/v1/catalog")
        assert response.status_code == 200, "public catalog must not require a login"
        body = response.json()
        assert body["releaseId"] == str(release.id)
        assert body["evaluatedOn"] == "2026-09-30"
        assert {item["name"] for item in body["items"]} == {
            "格蘭菲迪 12 年",
            "格蘭菲迪 15 年 Solera",
            "格蘭利威 12 年",
        }
        for item in body["items"]:
            assert item["bottleVersionId"]
            assert item["versionLabel"]
            assert item["claims"]
            assert all(claim["sources"] for claim in item["claims"])
            assert all(
                source["url"].startswith("https://") and source["checkedOn"]
                for claim in item["claims"]
                for source in claim["sources"]
            )
            assert all(
                tag["method"] and tag["methodVersion"] and tag["evidenceIds"]
                for tag in item["flavorTags"]
            )
        twelve = next(
            item for item in body["items"] if item["name"] == "格蘭菲迪 12 年"
        )
        assert twelve["priceUpperBoundTwd"] == "978"
        assert twelve["prices"][0]["market"] == "TW"
        assert twelve["prices"][0]["currency"] == "TWD"
        assert twelve["prices"][0]["volumeMl"] == 700
        fifteen = next(
            item for item in body["items"] if item["name"] == "格蘭菲迪 15 年 Solera"
        )
        assert fifteen["priceUpperBoundTwd"] is None
        assert fifteen["priceQualification"] == "unqualified"
        assert (await client.get("/api/v1/plans")).status_code == 401


async def test_missing_catalog_configuration_reports_unavailable_not_empty_success():
    async with AsyncClient(
        transport=ASGITransport(create_app()), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/catalog")
        assert response.status_code == 503
        assert response.json()["code"] == "CATALOG_UNAVAILABLE"


async def test_expired_reference_prices_remain_visible_but_never_budget_qualified(
    research_context, monkeypatch
):
    engine, _, _, _ = research_context
    CatalogStore(engine).publish(
        load_reviewed_release(
            (
                Path(__file__).parents[3] / "data/catalog/first-journey.reviewed.json"
            ).read_text()
        )
    )
    monkeypatch.setattr(
        "whisky.modules.catalog.public.taiwan_date", lambda _: date(2026, 11, 1)
    )
    app = configured_app(
        Settings(
            str(engine.url),
            "https://whisky-fixture.example/",
            "https://whisky-api.example",
        )
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://test") as client,
    ):
        response = await client.get("/api/v1/catalog")
        assert response.status_code == 200
        assert len(response.json()["items"]) == 3
        for item in response.json()["items"]:
            assert item["priceQualification"] == "unqualified"
            assert item["priceUpperBoundTwd"] is None
            assert item["prices"], "dated reference observations are retained"
            assert all(not price["qualified"] for price in item["prices"])
