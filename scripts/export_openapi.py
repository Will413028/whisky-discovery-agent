"""Export the API contract without connecting to databases or auth providers."""

import json
from pathlib import Path

from whisky.bootstrap.api import create_app
from whisky.modules.catalog.http import CatalogView
from whisky.modules.control.http import ControlView
from whisky.modules.discovery.http import PlanListView, PlanView
from whisky.modules.research.comparison_views_v4 import ComparisonReportViewV4
from whisky.modules.research.public import TaskView
from whisky.modules.research.views import TaskHistoryView

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
target.with_name("catalog-view.schema.json").write_text(
    json.dumps(
        CatalogView.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True
    )
    + "\n"
)
for name, model in (
    ("plan-view", PlanView),
    ("plan-list-view", PlanListView),
    ("control-view", ControlView),
    ("task-history-view", TaskHistoryView),
    ("comparison-report-view", ComparisonReportViewV4),
):
    target.with_name(f"{name}.schema.json").write_text(
        json.dumps(
            model.model_json_schema(mode="serialization"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
