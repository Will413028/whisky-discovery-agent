"""Export the API contract without connecting to databases or auth providers."""

import json
from pathlib import Path

from whisky.bootstrap.api import create_app
from whisky.modules.catalog.http import CatalogView
from whisky.modules.control.http import ControlView
from whisky.modules.discovery.http import PlanListView, PlanView
from whisky.modules.library.contracts import (
    BottleFeedbackListViewV1,
    BottleFeedbackViewV1,
    ConclusionContextViewV1,
    ConclusionListViewV1,
    ConclusionRevisitViewV1,
    ConclusionViewV1,
)
from whisky.modules.research.comparison_views_v4 import ComparisonReportViewV4
from whisky.modules.research.inputs_v4 import StartCommandV4
from whisky.modules.research.proposal_view_v4 import PreferenceProposalViewV4
from whisky.modules.research.public import TaskView
from whisky.modules.research.restart_context_v4 import RestartContextViewV4
from whisky.modules.research.views import TaskHistoryView

target = Path(__file__).resolve().parents[1] / "contracts/openapi.json"
target.parent.mkdir(exist_ok=True)
schema = create_app().openapi()
view = TaskView.model_json_schema(ref_template="#/components/schemas/{model}")
schema["components"]["schemas"].update(view.pop("$defs", {}))
schema["components"]["schemas"]["TaskView"] = view
start = StartCommandV4.model_json_schema(
    ref_template="#/components/schemas/{model}Input"
)
schema["components"]["schemas"].update(
    {f"{name}Input": definition for name, definition in start.pop("$defs", {}).items()}
)
schema["components"]["schemas"]["StartCommandV4"] = start
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
    ("preference-proposal-view", PreferenceProposalViewV4),
    ("restart-context-view", RestartContextViewV4),
    ("conclusion-view", ConclusionViewV1),
    ("conclusion-list-view", ConclusionListViewV1),
    ("conclusion-context-view", ConclusionContextViewV1),
    ("conclusion-revisit-view", ConclusionRevisitViewV1),
    ("bottle-feedback-view", BottleFeedbackViewV1),
    ("bottle-feedback-list-view", BottleFeedbackListViewV1),
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
