import pytest
from test_comparison_reports_v4 import comparison_commit as comparison_commit
from test_library_conclusions import completed_choice as completed_choice
from test_library_purge import delete

from whisky.modules.research.domain import workflow_id_for
from whisky.modules.research.history_cleanup_store import (
    deleted_history_page,
    history_erasure_allowed,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("kind", ["plan.delete", "actor.delete"])
def test_only_deleted_parent_tombstones_are_discovered(completed_choice, kind):
    engine, actor, report, choice = completed_choice
    assert deleted_history_page(engine).workflow_ids == ()
    delete(engine, actor, choice, kind)
    page = deleted_history_page(engine)
    assert page.workflow_ids == (workflow_id_for(report.task_id),)


@pytest.mark.parametrize("kind", ["plan.delete", "actor.delete"])
def test_each_erasure_rechecks_its_deleted_parent_scope(completed_choice, kind):
    engine, actor, report, choice = completed_choice
    identifier = workflow_id_for(report.task_id)
    assert not history_erasure_allowed(engine, identifier)
    delete(engine, actor, choice, kind)
    assert history_erasure_allowed(engine, identifier)
