"""A control intent must fence product writes before late work can commit."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import event, text

import whisky.modules.control.store as control_store_module
from whisky.modules.control.activities import ControlActivities
from whisky.modules.control.journal import MemoryControlJournal, result_record
from whisky.modules.control.store import ControlConflict, ControlStore
from whisky.modules.discovery.conditions import CatalogReference, ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.research.domain import workflow_id_for
from whisky.modules.research.report import ReportDraft
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.store import ResearchConflict
from whisky.platform.domain_errors import DomainRejection

pytestmark = pytest.mark.integration


def _task(research, actor, plan, key):
    receipt = research.reserve(actor.id, actor.generation, plan.id, 1, key)
    research.confirm(actor.id, actor.generation, receipt.id, str(uuid4()))
    return receipt.task_id


def _control_key():
    return str(uuid4())


def test_control_key_must_be_an_opaque_uuid(research_context):
    engine, research, (actor, _), plan = research_context
    task_id = _task(research, actor, plan, "invalid-control-key")
    with pytest.raises(ValueError, match="UUID"):
        ControlStore(engine).reserve(
            actor.id, actor.generation, "task.cancel", task_id, "my private note"
        )


def test_cancel_requires_confirmed_external_intent_and_fences_late_report(
    research_context,
):
    engine, research, (actor, _), plan = research_context
    task_id = _task(research, actor, plan, "cancel-late")
    controls = ControlStore(engine)
    command = controls.reserve(
        actor.id, actor.generation, "task.cancel", task_id, _control_key()
    )
    with pytest.raises(ControlConflict, match="INTENT_UNCONFIRMED"):
        controls.apply(command.id)
    assert research.task(task_id, actor.id).status == "queued"

    controls.confirm_intent(command.id)
    applied = controls.apply(command.id)
    assert applied.status == "effect_applied"
    assert research.task(task_id, actor.id).status == "cancelled"
    with pytest.raises(ResearchConflict, match="TASK_NOT_WRITABLE"):
        ReportStore(engine).save(
            actor.id,
            actor.generation,
            task_id,
            "late-report",
            ReportDraft(summary="晚到報告", candidates=()),
            policy_version="price-30d-v1",
            prompt_version="research-v1",
            model_version="fixture-v1",
        )
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM research_reports")) == 0
    assert controls.read(command.id, actor.id).status == "effect_applied"
    assert controls.confirm_result(command.id).status == "completed"


def test_condition_change_supersedes_open_work_but_preserves_completed_report(
    research_context,
):
    engine, research, (actor, _), plan = research_context
    open_task = _task(research, actor, plan, "old-open")
    finished_task = _task(research, actor, plan, "old-finished")
    question_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO clarifications
                (id,task_id,owner_id,generation,conditions_revision,
                 waiting_version,prompt,choices,status,expires_at)
            VALUES (:question,:task,:owner,:generation,1,1,'選擇版本',
                    CAST('["one","two"]' AS jsonb),'pending',now()+interval '1 day')
            """),
            dict(
                question=question_id,
                task=open_task,
                owner=actor.id,
                generation=actor.generation,
            ),
        )
        connection.execute(
            text("""
            UPDATE research_tasks SET status='needs_input',active_question_id=:question,
                question=CAST('{"prompt":"選擇版本"}' AS jsonb)
            WHERE id=:task
            """),
            dict(question=question_id, task=open_task),
        )
    report = ReportStore(engine).save(
        actor.id,
        actor.generation,
        finished_task,
        "finished",
        ReportDraft(summary="舊條件下的報告", candidates=()),
        policy_version="price-30d-v1",
        prompt_version="research-v1",
        model_version="fixture-v1",
    )
    changed = ResearchConditions(entry="beginner", goal="探索煙燻風味")
    controls = ControlStore(engine)
    command = controls.reserve(
        actor.id,
        actor.generation,
        "plan.change_conditions",
        plan.id,
        _control_key(),
        expected_revision=1,
        conditions=changed,
    )
    controls.confirm_intent(command.id)
    controls.apply(command.id)
    controls.confirm_result(command.id)
    latest = PlanStore(engine).read(plan.id, actor.id)
    assert latest.conditions_revision == 2
    assert latest.conditions == changed
    assert research.task(open_task, actor.id).status == "superseded"
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT status FROM clarifications WHERE id=:question"),
                dict(question=question_id),
            )
            == "closed"
        )
        assert (
            connection.scalar(
                text("SELECT active_question_id FROM research_tasks WHERE id=:task"),
                dict(task=open_task),
            )
            is None
        )
    assert research.task(finished_task, actor.id).status == "completed"
    assert ReportStore(engine).read(actor.id, report.id) is not None
    with pytest.raises(ResearchConflict, match="REVISION_CONFLICT"):
        research.reserve(actor.id, actor.generation, plan.id, 1, "late-start")
    assert research.reserve(actor.id, actor.generation, plan.id, 2, "new-start")


def test_plan_and_actor_delete_fence_all_descendants_and_new_instance_survives(
    research_context,
):
    engine, research, (actor, _), old_plan = research_context
    first = _task(research, actor, old_plan, "delete-first")
    second = _task(research, actor, old_plan, "delete-second")
    controls = ControlStore(engine)
    delete_plan = controls.reserve(
        actor.id, actor.generation, "plan.delete", old_plan.id, _control_key()
    )
    controls.confirm_intent(delete_plan.id)
    controls.apply(delete_plan.id)
    controls.confirm_result(delete_plan.id)
    assert research.task(first, actor.id).status == "cancelled"
    assert research.task(second, actor.id).status == "cancelled"
    assert PlanStore(engine).read(old_plan.id, actor.id) is None
    with pytest.raises(ResearchConflict, match="NOT_FOUND"):
        research.reserve(actor.id, actor.generation, old_plan.id, 1, "late-old")

    new_plan = PlanStore(engine).create(
        actor.id,
        actor.generation,
        "new-instance",
        ResearchConditions(entry="beginner", goal="新委託"),
    )
    new_task = _task(research, actor, new_plan, "new-task")
    assert research.task(new_task, actor.id).status == "queued"
    controls.apply(delete_plan.id)
    assert research.task(new_task, actor.id).status == "queued"

    delete_actor = controls.reserve(
        actor.id, actor.generation, "actor.delete", actor.id, _control_key()
    )
    controls.confirm_intent(delete_actor.id)
    controls.apply(delete_actor.id)
    controls.confirm_result(delete_actor.id)
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT write_allowed FROM research_tasks WHERE id=:id"),
                {"id": new_task},
            )
            is False
        )
        assert (
            connection.scalar(
                text("SELECT active FROM users WHERE id=:id"), {"id": actor.id}
            )
            is False
        )


@pytest.mark.asyncio
async def test_external_result_failure_keeps_effect_unconfirmed_and_replays(
    research_context,
):
    engine, research, (actor, _), plan = research_context
    task_id = _task(research, actor, plan, "result-failure")
    controls = ControlStore(engine)
    journal = MemoryControlJournal()
    activities = ControlActivities(controls, journal)
    command = controls.reserve(
        actor.id, actor.generation, "task.cancel", task_id, _control_key()
    )
    await activities.persist_intent(str(command.id))
    await activities.apply_effect(str(command.id))
    journal.fail_before_write = True
    with pytest.raises(OSError, match="unavailable"):
        await activities.persist_result(str(command.id))
    assert controls.read(command.id, actor.id).status == "effect_applied"
    assert research.task(task_id, actor.id).status == "cancelled"
    journal.fail_before_write = False
    assert await activities.persist_result(str(command.id)) == "completed"
    assert await activities.persist_result(str(command.id)) == "completed"
    assert controls.read(command.id, actor.id).status == "completed"
    assert len(journal.objects) == 2


@pytest.mark.asyncio
async def test_rejected_revision_is_recorded_as_rejection_not_completion(
    research_context,
):
    engine, _, (actor, _), plan = research_context
    controls = ControlStore(engine)
    command = controls.reserve(
        actor.id,
        actor.generation,
        "plan.change_conditions",
        plan.id,
        _control_key(),
        expected_revision=1,
        conditions=ResearchConditions(entry="beginner", goal="新條件"),
    )
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE plans SET conditions_revision=2 WHERE id=:id"),
            dict(id=plan.id),
        )
    journal = MemoryControlJournal()
    activities = ControlActivities(controls, journal)
    await activities.persist_intent(str(command.id))
    assert await activities.apply_effect(str(command.id)) == "effect_rejected"
    assert await activities.persist_result(str(command.id)) == "rejected"
    rejected = controls.read(command.id, actor.id)
    assert rejected.status == "rejected"
    assert rejected.result["code"] == "REVISION_CONFLICT"
    key, body = result_record(rejected)
    assert journal.read(key) == body
    assert b'"outcome":"rejected"' in body


def test_rejected_condition_change_can_be_corrected_at_same_revision(research_context):
    engine, _, (actor, _), plan = research_context
    controls = ControlStore(engine)
    invalid = controls.reserve(
        actor.id,
        actor.generation,
        "plan.change_conditions",
        plan.id,
        _control_key(),
        expected_revision=1,
        conditions=ResearchConditions(
            entry="existing_bottle",
            goal="待修正版本",
            starting_bottle=CatalogReference(release_id=uuid4(), item_id=uuid4()),
        ),
    )
    controls.confirm_intent(invalid.id)
    assert controls.apply(invalid.id).status == "effect_rejected"
    assert controls.confirm_result(invalid.id).status == "rejected"
    assert PlanStore(engine).read(plan.id, actor.id).conditions_revision == 1

    corrected = controls.reserve(
        actor.id,
        actor.generation,
        "plan.change_conditions",
        plan.id,
        _control_key(),
        expected_revision=1,
        conditions=ResearchConditions(entry="beginner", goal="修正後研究"),
    )
    assert corrected.id != invalid.id
    assert corrected.workflow_id != invalid.workflow_id
    controls.confirm_intent(corrected.id)
    assert controls.apply(corrected.id).status == "effect_applied"
    assert PlanStore(engine).read(plan.id, actor.id).conditions_revision == 2


def test_untyped_error_after_condition_write_rolls_back_instead_of_rejecting(
    research_context, monkeypatch
):
    engine, _, (actor, _), plan = research_context
    controls = ControlStore(engine)
    command = controls.reserve(
        actor.id,
        actor.generation,
        "plan.change_conditions",
        plan.id,
        _control_key(),
        expected_revision=1,
        conditions=ResearchConditions(entry="beginner", goal="下一版"),
    )
    controls.confirm_intent(command.id)

    def unexpected_error(*_args, **_kwargs):
        raise ValueError("REVISION_CONFLICT")

    monkeypatch.setattr(control_store_module, "close_plan_tasks", unexpected_error)
    with pytest.raises(ValueError, match="REVISION_CONFLICT"):
        controls.apply(command.id)
    assert controls.read(command.id, actor.id).status == "intent_confirmed"
    assert PlanStore(engine).read(plan.id, actor.id).conditions_revision == 1


def test_typed_rejection_after_partial_effect_does_not_commit_child_writes(
    research_context, monkeypatch
):
    engine, _, (actor, _), plan = research_context
    controls = ControlStore(engine)
    command = controls.reserve(
        actor.id,
        actor.generation,
        "plan.change_conditions",
        plan.id,
        _control_key(),
        expected_revision=1,
        conditions=ResearchConditions(entry="beginner", goal="下一版"),
    )
    controls.confirm_intent(command.id)

    def reject_after_change(*_args, **_kwargs):
        raise DomainRejection("REVISION_CONFLICT")

    monkeypatch.setattr(control_store_module, "close_plan_tasks", reject_after_change)
    rejected = controls.apply(command.id)
    assert rejected.status == "effect_rejected"
    assert PlanStore(engine).read(plan.id, actor.id).conditions_revision == 1


@pytest.mark.asyncio
async def test_control_notifies_old_research_after_the_fence(research_context):
    engine, research, (actor, _), plan = research_context
    task_id = _task(research, actor, plan, "notify")
    controls = ControlStore(engine)
    command = controls.reserve(
        actor.id, actor.generation, "task.cancel", task_id, _control_key()
    )

    class Canceller:
        def __init__(self):
            self.ids = []

        async def cancel(self, workflow_id):
            assert research.task(task_id, actor.id).status == "cancelled"
            self.ids.append(workflow_id)

    notifier = Canceller()
    activities = ControlActivities(controls, MemoryControlJournal(), notifier)
    await activities.persist_intent(str(command.id))
    await activities.apply_effect(str(command.id))
    await activities.persist_result(str(command.id))
    await activities.notify_research(str(command.id))
    assert notifier.ids == [workflow_id_for(task_id)]


def test_actor_delete_fences_descendants_from_older_identity_generations(
    research_context,
):
    engine, research, (actor, _), old_plan = research_context
    old_task = _task(research, actor, old_plan, "previous-generation")
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE users SET generation=2 WHERE id=:owner"),
            dict(owner=actor.id),
        )
    controls = ControlStore(engine)
    command = controls.reserve(actor.id, 2, "actor.delete", actor.id, _control_key())
    controls.confirm_intent(command.id)
    controls.apply(command.id)
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT write_allowed FROM research_tasks WHERE id=:task"),
                dict(task=old_task),
            )
            is False
        )
        assert (
            connection.scalar(
                text("SELECT deleted_at IS NOT NULL FROM plans WHERE id=:plan"),
                dict(plan=old_plan.id),
            )
            is True
        )


def test_actor_delete_rolls_back_all_descendants_if_identity_final_step_fails(
    research_context, monkeypatch
):
    engine, research, (actor, _), plan = research_context
    task_id = _task(research, actor, plan, "rollback-actor-delete")
    controls = ControlStore(engine)
    command = controls.reserve(
        actor.id, actor.generation, "actor.delete", actor.id, _control_key()
    )
    controls.confirm_intent(command.id)

    def fail_identity(_connection, _actor_id, _generation):
        raise ValueError("IDENTITY_CHANGED")

    monkeypatch.setattr(control_store_module, "disable_actor", fail_identity)
    with pytest.raises(RuntimeError, match="identity changed"):
        controls.apply(command.id)
    assert controls.read(command.id, actor.id).status == "intent_confirmed"
    assert research.task(task_id, actor.id).status == "queued"
    assert PlanStore(engine).read(plan.id, actor.id) is not None


def test_cancel_lock_wins_before_late_report_on_two_connections(research_context):
    engine, research, (actor, _), plan = research_context
    task_id = _task(research, actor, plan, "racing-report")
    controls = ControlStore(engine)
    command = controls.reserve(
        actor.id, actor.generation, "task.cancel", task_id, _control_key()
    )
    controls.confirm_intent(command.id)
    cancel_has_locks = Event()
    release_cancel = Event()
    report_attempted = Event()

    def hold_cancel(_conn, _cursor, statement, _params, _context, _many):
        if "UPDATE research_tasks SET status='cancelled'" in statement:
            cancel_has_locks.set()
            assert release_cancel.wait(10), "report never reached the race barrier"

    def late_report():
        report_attempted.set()
        return ReportStore(engine).save(
            actor.id,
            actor.generation,
            task_id,
            "racing-final",
            ReportDraft(summary="晚到結果", candidates=()),
            policy_version="price-30d-v1",
            prompt_version="research-v1",
            model_version="fixture-v1",
        )

    event.listen(engine, "before_cursor_execute", hold_cancel)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            cancelling = executor.submit(controls.apply, command.id)
            assert cancel_has_locks.wait(10), "control did not reach its fence"
            reporting = executor.submit(late_report)
            assert report_attempted.wait(10)
            release_cancel.set()
            assert cancelling.result(timeout=10).status == "effect_applied"
            with pytest.raises(ResearchConflict, match="TASK_NOT_WRITABLE"):
                reporting.result(timeout=10)
    finally:
        release_cancel.set()
        event.remove(engine, "before_cursor_execute", hold_cancel)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM research_reports")) == 0


def test_cancel_replaces_an_old_interrupt_turn_with_terminal_outcome(
    research_context,
):
    engine, research, (actor, _), plan = research_context
    started = research.reserve(actor.id, actor.generation, plan.id, 1, "interrupt")
    with engine.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO agent_turns
                (owner_id,task_id,thread_id,run_id,command_id,outcome)
            SELECT t.owner_id,t.id,t.thread_id,:run,:command,
                   CAST('{"type":"interrupt"}' AS jsonb)
            FROM research_tasks t WHERE t.id=:task
            """),
            dict(run=uuid4(), command=started.id, task=started.task_id),
        )
    controls = ControlStore(engine)
    command = controls.reserve(
        actor.id,
        actor.generation,
        "task.cancel",
        started.task_id,
        _control_key(),
    )
    controls.confirm_intent(command.id)
    controls.apply(command.id)
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT outcome->>'type' FROM agent_turns WHERE task_id=:task"),
                dict(task=started.task_id),
            )
            == "error"
        )
