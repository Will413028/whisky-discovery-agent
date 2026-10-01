"""Deleted parents must erase research originals while retaining write fences."""

import json

import pytest
from sqlalchemy import text
from test_account_export_store import populate
from test_comparison_reports_v4 import comparison_commit as comparison_commit
from test_control_recovery import PagedJournal
from test_library_conclusions import completed_choice as completed_choice
from test_library_purge import delete
from test_research_quota import ready_task

import whisky.modules.control.store as control_module
from whisky.modules.control.recovery import reconcile_control_log
from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.research.public import purge_actor_research, purge_plan_research
from whisky.modules.research.quota import QuotaStore

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("kind", ["plan.delete", "actor.delete"])
def test_other_accounts_task_originals_survive_delete(
    completed_choice, research_context, kind
):
    engine, actor, _, choice = completed_choice
    _, research, (_, other), _ = research_context
    plan = PlanStore(engine).create(
        other.id,
        other.generation,
        "other",
        ResearchConditions(entry="beginner", goal="另一個帳號的原文"),
    )
    task = ready_task(engine, research, other, plan, "foreign-original")
    delete(engine, actor, choice, kind)
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT conditions,write_allowed FROM research_tasks WHERE id=:task"),
            dict(task=task),
        ).one()
        assert row.conditions["goal"] == "另一個帳號的原文"
        assert row.write_allowed is True


@pytest.mark.parametrize("kind", ["plan.delete", "actor.delete"])
def test_live_parent_cannot_erase_research_originals(completed_choice, kind):
    engine, actor, report, choice = completed_choice
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="fence"):
            if kind == "plan.delete":
                purge_plan_research(
                    connection, actor.id, actor.generation, choice.plan_id
                )
            else:
                purge_actor_research(connection, actor.id, actor.generation)
        assert (
            connection.scalar(
                text("SELECT count(*) FROM research_reports WHERE id=:report"),
                dict(report=report.id),
            )
            == 1
        )


def test_research_cleanup_failure_rolls_back_parent_and_library(
    completed_choice, monkeypatch
):
    engine, actor, _ = populate(completed_choice)
    _, _, report, choice = completed_choice
    original = control_module.purge_actor_research

    def fail_after_cleanup(*args):
        original(*args)
        raise RuntimeError("synthetic research cleanup failure")

    monkeypatch.setattr(control_module, "purge_actor_research", fail_after_cleanup)
    with pytest.raises(RuntimeError, match="synthetic research"):
        delete(engine, actor, choice, "actor.delete")
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT active FROM users WHERE id=:owner"), dict(owner=actor.id)
            )
            is True
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM library_conclusions WHERE owner_id=:owner"),
                dict(owner=actor.id),
            )
            == 1
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM research_reports WHERE id=:report"),
                dict(report=report.id),
            )
            == 1
        )


def test_active_provider_usage_can_finish_after_originals_are_erased(
    completed_choice, research_context
):
    engine, actor, _, choice = completed_choice
    _, research, _, plan = research_context
    task = ready_task(engine, research, actor, plan, "active-erasure")
    quota = QuotaStore(engine, daily_neuron_limit=2000)
    active = quota.reserve(task, "active", 1, "model", 100, 500)
    finished = quota.reserve(task, "finished", 1, "model", 100, 500)
    quota.finish(finished.id, known=False)
    before = quota.daily_reserved_neurons()
    delete(engine, actor, choice, "plan.delete")
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM research_usage_attempts WHERE id=:id"),
                dict(id=active.id),
            )
            == 1
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM research_usage_attempts WHERE id=:id"),
                dict(id=finished.id),
            )
            == 0
        )
    quota.finish(active.id, known=True, input_tokens=1000, output_tokens=1000)
    assert quota.daily_reserved_neurons() > before


@pytest.mark.parametrize("kind", ["plan.delete", "actor.delete"])
def test_deleted_parent_erases_report_and_task_originals(completed_choice, kind):
    engine, actor, _ = populate(completed_choice)
    _, _, report, choice = completed_choice
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM research_reports WHERE id=:report"),
                dict(report=report.id),
            )
            == 1
        )
    delete(engine, actor, choice, kind)
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM research_reports WHERE id=:report"),
                dict(report=report.id),
            )
            == 0
        )
        task = connection.execute(
            text("""
                SELECT conditions,status,write_allowed,report_id,question,error
                FROM research_tasks WHERE id=:task
            """),
            dict(task=report.task_id),
        ).one()
        assert task.conditions == {}
        assert task.status == "cancelled"
        assert task.write_allowed is False
        assert task.report_id is task.question is task.error is None


@pytest.mark.parametrize("kind", ["plan.delete", "actor.delete"])
def test_restored_task_originals_are_erased_under_surviving_delete(
    completed_choice, kind
):
    engine, actor, _ = populate(completed_choice)
    _, _, report, choice = completed_choice
    with engine.connect() as connection:
        original = connection.scalar(
            text("SELECT conditions FROM research_tasks WHERE id=:task"),
            dict(task=report.task_id),
        )
    assert original
    journal = PagedJournal()
    controls, _ = delete(engine, actor, choice, kind, journal)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE research_tasks SET conditions=CAST(:raw AS jsonb) "
                "WHERE id=:task"
            ),
            dict(raw=json.dumps(original), task=report.task_id),
        )
    reconcile_control_log(journal, controls)
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT conditions FROM research_tasks WHERE id=:task"),
                dict(task=report.task_id),
            )
            == {}
        )
