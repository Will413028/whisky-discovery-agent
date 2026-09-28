"""Export the API contract without connecting to databases or auth providers."""

import json
from pathlib import Path

from whisky.bootstrap.api import create_app

target = Path(__file__).resolve().parents[1] / "contracts/openapi.json"
target.parent.mkdir(exist_ok=True)
target.write_text(
    json.dumps(create_app().openapi(), ensure_ascii=False, indent=2, sort_keys=True)
    + "\n"
)
