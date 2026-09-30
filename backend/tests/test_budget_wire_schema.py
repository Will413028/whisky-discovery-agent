"""Response metadata must describe the existing, unchanged V1 serializer."""

import re
from decimal import Decimal

from whisky.modules.discovery.conditions_v1 import ResearchConditions


def test_budget_response_schema_rejects_non_numeric_text_and_keeps_v1_wire_values():
    schema = ResearchConditions.model_json_schema(mode="serialization")
    branches = schema["properties"]["budget_twd"]["anyOf"]
    text = next(branch for branch in branches if branch.get("type") == "string")
    assert "pattern" in text, "Budget wire schema must reject non-numeric strings"
    pattern = re.compile(text["pattern"])
    for value, expected in (
        ("1E+3", "1000"),
        ("1000.2500", "1000.25"),
        ("0.01", "0.01"),
        ("9999999999999999.99", "9999999999999999.99"),
    ):
        conditions = ResearchConditions(
            entry="beginner", goal="果香", budget_twd=Decimal(value)
        )
        wire = conditions.model_dump(mode="json")["budget_twd"]
        assert wire == expected
        assert pattern.search(wire)
    for malformed in ("not-money", "1000junk", "", "NaN", "Infinity"):
        assert not pattern.search(malformed)
