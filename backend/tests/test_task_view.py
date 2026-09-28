import pytest
from pydantic import ValidationError

from whisky.modules.research.views import TaskView


def snapshot(**changes):
    data = dict(
        taskId="00000000-0000-4000-8000-000000000001",
        threadId="00000000-0000-4000-8000-000000000002",
        conditionsRevision=1,
        viewVersion=1,
        status="researching",
        stage="查核來源",
        question=None,
        reportId=None,
        error=None,
        observedAt="2026-09-28T00:00:00Z",
    )
    return {**data, **changes}


@pytest.mark.parametrize("status", ["needs_input", "completed", "failed"])
def test_status_requires_its_saved_payload(status):
    with pytest.raises(ValidationError):
        TaskView.model_validate(snapshot(status=status))


def test_researching_snapshot_has_no_terminal_payload():
    view = TaskView.model_validate(snapshot())
    assert view.status == "researching"
    assert view.model_dump(by_alias=True)["viewVersion"] == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"viewVersion": 0},
        {"conditionsRevision": 0},
        {"schemaVersion": 2},
        {"observedAt": "2026-09-28T00:00:00"},
        {"reportId": "00000000-0000-4000-8000-000000000003"},
    ],
)
def test_invalid_or_inconsistent_snapshot_is_rejected(changes):
    with pytest.raises(ValidationError):
        TaskView.model_validate(snapshot(**changes))
