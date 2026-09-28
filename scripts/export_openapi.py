"""Export the API contract without connecting to databases or auth providers."""

import json
from pathlib import Path

from whisky.bootstrap.api import create_app
from whisky.modules.research.public import TaskView

target = Path(__file__).resolve().parents[1] / "contracts/openapi.json"
target.parent.mkdir(exist_ok=True)
schema = create_app().openapi()
view = TaskView.model_json_schema(ref_template="#/components/schemas/{model}")
schema["components"]["schemas"].update(view.pop("$defs", {}))
schema["components"]["schemas"]["TaskView"] = view
target.write_text(
    json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
)
target.with_name("task-view.schema.json").write_text(
    json.dumps(
        TaskView.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True
    )
    + "\n"
)
