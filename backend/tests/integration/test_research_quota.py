"""Quota reservations must survive processes and serialize independent DB clients."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import text

from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.identity.store import IdentityStore
from whisky.modules.identity.tokens import Principal
from whisky.modules.research.quota import QuotaError, QuotaStore, reserved_neurons
from whisky.modules.research.run_store import ResearchRunStore

pytestmark = pytest.mark.integration


def test_reservations_use_the_selected_models_published_neuron_rates():
    glm = reserved_neurons(1_000_000, 1_000_000, model_name="@cf/zai-org/glm-4.7-flash")
    qwen = reserved_neurons(
        1_000_000, 1_000_000, model_name="@cf/qwen/qwen3-30b-a3b-fp8"
    )
    llama = reserved_neurons(
        1_000_000,
        1_000_000,
        model_name="@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    )
    gpt_oss = reserved_neurons(
        1_000_000, 1_000_000, model_name="@cf/openai/gpt-oss-20b"
    )
    assert glm == 5_500 + 36_400
    assert qwen == 4_625 + 30_475
    assert llama == 26_668 + 204_805
    assert gpt_oss == 18_182 + 27_273


def ready_task(engine, research, actor, plan, key):
    receipt = research.reserve(actor.id, actor.generation, plan.id, 1, key)
    research.confirm(actor.id, actor.generation, receipt.id, f"run-{key}")
    ResearchRunStore(engine).begin(receipt.task_id)
    return receipt.task_id


def test_global_slots_are_transactional_under_three_competing_clients(research_context):
    engine, research, (first, second), first_plan = research_context
    actors = [first, second]
    actors.append(
        IdentityStore(engine).resolve(
            Principal("https://research-fixture.example/", "quota-third")
        )
    )
    plans = [first_plan]
    for actor in actors[1:]:
        plans.append(
            PlanStore(engine).create(
                actor.id,
                actor.generation,
                "quota",
                ResearchConditions(entry="beginner", goal="探索果香"),
            )
        )
    tasks = [
        ready_task(engine, research, actor, plan, f"global-{index}")
        for index, (actor, plan) in enumerate(zip(actors, plans))
    ]
    barrier = Barrier(3)

    def compete(index):
        barrier.wait()
        try:
            return QuotaStore(engine, daily_neuron_limit=1000).reserve(
                tasks[index], f"model-{index}", 1, "model", 100, 500
            )
        except QuotaError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=3) as pool:
        outcomes = list(pool.map(compete, range(3)))
    assert sum(not isinstance(outcome, str) for outcome in outcomes) == 2
    assert outcomes.count("GLOBAL_CONCURRENCY_LIMIT") == 1


def test_one_account_cannot_run_two_tasks_even_with_free_global_slot(research_context):
    engine, research, (actor, _), plan = research_context
    first = ready_task(engine, research, actor, plan, "same-owner-1")
    second = ready_task(engine, research, actor, plan, "same-owner-2")
    quota = QuotaStore(engine, daily_neuron_limit=1000)
    reservation = quota.reserve(first, "first-model", 1, "model", 100, 500)
    with pytest.raises(QuotaError, match="OWNER_CONCURRENCY_LIMIT"):
        quota.reserve(second, "second-model", 1, "model", 100, 500)
    quota.finish(reservation.id, known=True, input_tokens=80, output_tokens=20)
    assert quota.reserve(second, "second-model", 1, "model", 100, 500)


def test_account_daily_usage_spans_tasks_without_consuming_another_accounts_budget(
    research_context,
):
    engine, research, (first_actor, second_actor), first_plan = research_context
    second_plan = PlanStore(engine).create(
        second_actor.id,
        second_actor.generation,
        "quota other account",
        ResearchConditions(entry="beginner", goal="探索果香"),
    )
    first_task = ready_task(engine, research, first_actor, first_plan, "account-day-1")
    second_task = ready_task(engine, research, first_actor, first_plan, "account-day-2")
    other_task = ready_task(engine, research, second_actor, second_plan, "other-day")
    quota = QuotaStore(engine, daily_neuron_limit=2000)
    first = quota.reserve(first_task, "first-model", 1, "model", 10_000, 16_000)
    quota.finish(first.id, known=False)
    assert first.reserved_neurons == 534
    with pytest.raises(QuotaError, match="OWNER_DAILY_BUDGET_EXHAUSTED"):
        quota.reserve(second_task, "second-model", 1, "model", 10_000, 16_000)
    assert quota.reserve(other_task, "other-model", 1, "model", 100, 500)
    assert quota.daily_reserved_neurons() > first.reserved_neurons


def test_same_account_parallel_reservations_cannot_cross_daily_cap(
    research_context,
):
    engine, research, (actor, _), plan = research_context
    task = ready_task(engine, research, actor, plan, "account-race")
    barrier = Barrier(2)

    def compete(index):
        barrier.wait()
        try:
            return QuotaStore(
                engine, daily_neuron_limit=2000, max_output_tokens=32_000
            ).reserve(task, f"parallel-{index}", 1, "model", 10_000, 16_000)
        except QuotaError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(compete, range(2)))
    assert sum(not isinstance(outcome, str) for outcome in outcomes) == 1
    assert outcomes.count("OWNER_DAILY_BUDGET_EXHAUSTED") == 1
    assert QuotaStore(engine, daily_neuron_limit=2000).daily_reserved_neurons() == 534


def test_retry_and_crash_keep_daily_reservation_and_task_attempt_count(
    research_context,
):
    engine, research, (actor, _), plan = research_context
    task = ready_task(engine, research, actor, plan, "retry")
    first_store = QuotaStore(engine, daily_neuron_limit=100, max_model_requests=2)
    first = first_store.reserve(task, "same-activity", 1, "model", 100, 500)
    assert (
        first_store.reserve(task, "same-activity", 1, "model", 100, 500).id == first.id
    )
    assert first_store.daily_reserved_neurons() == first.reserved_neurons

    # Simulate a lost worker before finish: a fresh process sees the reservation.
    restarted = QuotaStore(engine, daily_neuron_limit=100, max_model_requests=2)
    second = restarted.reserve(task, "same-activity", 2, "model", 100, 500)
    assert second.id != first.id
    assert restarted.attempt(first.id).status == "unknown"
    assert restarted.daily_reserved_neurons() == (
        first.reserved_neurons + second.reserved_neurons
    )
    restarted.finish(second.id, known=False)
    assert restarted.daily_reserved_neurons() == (
        first.reserved_neurons + second.reserved_neurons
    )
    with pytest.raises(QuotaError, match="TASK_MODEL_LIMIT"):
        restarted.reserve(task, "next-activity", 1, "model", 100, 500)


def test_completion_uses_the_model_rate_saved_with_the_attempt(research_context):
    engine, research, (actor, _), plan = research_context
    task = ready_task(engine, research, actor, plan, "model-rate")
    qwen_model = "@cf/qwen/qwen3-30b-a3b-fp8"
    qwen = QuotaStore(engine, daily_neuron_limit=1000, model_name=qwen_model)
    reservation = qwen.reserve(task, "model", 1, "model", 100, 500)
    QuotaStore(engine, daily_neuron_limit=1000).finish(
        reservation.id, known=True, input_tokens=1000, output_tokens=1000
    )
    assert qwen.daily_reserved_neurons() == reserved_neurons(
        1000, 1000, model_name=qwen_model
    )


def test_exhausted_retry_retires_prior_active_slot_without_refunding(research_context):
    engine, research, (actor, _), plan = research_context
    first_task = ready_task(engine, research, actor, plan, "retry-exhausted")
    second_task = ready_task(engine, research, actor, plan, "after-exhausted")
    quota = QuotaStore(engine, daily_neuron_limit=100, max_model_requests=1)
    first = quota.reserve(first_task, "activity", 1, "model", 100, 500)
    with pytest.raises(QuotaError, match="TASK_MODEL_LIMIT"):
        quota.reserve(first_task, "activity", 2, "model", 100, 500)
    assert quota.attempt(first.id).status == "unknown"
    assert quota.daily_reserved_neurons() == first.reserved_neurons
    assert quota.reserve(second_task, "new-activity", 1, "model", 100, 500)


def test_missing_daily_budget_and_task_token_caps_fail_closed(research_context):
    engine, research, (actor, _), plan = research_context
    task = ready_task(engine, research, actor, plan, "hard-stop")
    with pytest.raises(QuotaError, match="DAILY_BUDGET_UNCONFIGURED"):
        QuotaStore(engine, daily_neuron_limit=0).reserve(
            task, "model", 1, "model", 100, 500
        )
    quota = QuotaStore(engine, daily_neuron_limit=2000)
    with pytest.raises(QuotaError, match="TASK_INPUT_TOKEN_LIMIT"):
        quota.reserve(task, "too-large", 1, "model", 100_001, 500)
    with pytest.raises(QuotaError, match="TASK_OUTPUT_TOKEN_LIMIT"):
        quota.reserve(task, "too-much-output", 1, "model", 100, 16_001)
    assert quota.daily_reserved_neurons() == 0
    within_input = quota.reserve(task, "within-input-cap", 1, "model", 100_000, 500)
    quota.finish(within_input.id, known=False)
    next_task = ready_task(engine, research, actor, plan, "output-cap")
    assert quota.reserve(next_task, "within-output-cap", 1, "model", 100, 16_000)


def test_waiting_does_not_hold_active_slot_after_io_completion(research_context):
    engine, research, (actor, _), plan = research_context
    first = ready_task(engine, research, actor, plan, "wait-slot-1")
    second = ready_task(engine, research, actor, plan, "wait-slot-2")
    quota = QuotaStore(engine, daily_neuron_limit=1000)
    reservation = quota.reserve(first, "reader", 1, "reader", 0, 0)
    quota.finish(reservation.id, known=True)
    assert quota.reserve(second, "reader-next", 1, "reader", 0, 0)


def test_cancelled_or_timed_out_attempts_release_slots_without_refund(research_context):
    engine, research, (actor, _), plan = research_context
    cancelled = ready_task(engine, research, actor, plan, "cancelled-active")
    next_task = ready_task(engine, research, actor, plan, "after-cancelled")
    quota = QuotaStore(engine, daily_neuron_limit=1000, max_active=1)
    first = quota.reserve(cancelled, "model-1", 1, "model", 100, 500)
    with engine.begin() as connection:
        connection.execute(
            text("""UPDATE research_tasks SET status='cancelled',write_allowed=false
            WHERE id=:task"""),
            dict(task=cancelled),
        )
    second = quota.reserve(next_task, "model-2", 1, "model", 100, 500)
    assert quota.attempt(first.id).status == "unknown"
    assert quota.daily_reserved_neurons() == (
        first.reserved_neurons + second.reserved_neurons
    )
    quota.finish(second.id, known=False)
    stale = quota.reserve(next_task, "model-3", 1, "model", 100, 500)
    with engine.begin() as connection:
        connection.execute(
            text("""UPDATE research_usage_attempts
            SET started_at=now()-interval '11 minutes' WHERE id=:id"""),
            dict(id=stale.id),
        )
    quota.reserve(next_task, "model-4", 1, "model", 100, 500)
    assert quota.attempt(stale.id).status == "unknown"
