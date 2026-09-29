"""PostgreSQL-backed reservations for each durable I/O activity attempt.

Reservations are deliberately conservative: an unknown provider result retains
its full daily and task charge. Temporal retry attempts have distinct rows.
"""

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, text

from whisky.modules.discovery.public import locked_plan
from whisky.modules.identity.public import actor_generation

FREE_DAILY_NEURONS = 10_000
DEFAULT_OWNER_DAILY_NEURONS = 1_000
DEFAULT_MODEL = "@cf/qwen/qwen3-30b-a3b-fp8"
MODEL_NEURON_RATES = {
    "@cf/zai-org/glm-4.7-flash": (5_500, 36_400),
    DEFAULT_MODEL: (4_625, 30_475),
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast": (26_668, 204_805),
    "@cf/openai/gpt-oss-20b": (18_182, 27_273),
}


class QuotaError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class QuotaReservation:
    id: UUID
    task_id: UUID
    activity_id: str
    attempt: int
    kind: str
    status: str
    reserved_neurons: int


def reserved_neurons(
    input_tokens: int, output_tokens: int, *, model_name: str = DEFAULT_MODEL
) -> int:
    input_rate, output_rate = MODEL_NEURON_RATES[model_name]
    numerator = input_tokens * input_rate + output_tokens * output_rate
    return max(1, (numerator + 999_999) // 1_000_000)


class QuotaStore:
    def __init__(
        self,
        engine: Engine,
        *,
        daily_neuron_limit: int,
        max_owner_daily_neurons: int = DEFAULT_OWNER_DAILY_NEURONS,
        max_active: int = 2,
        max_model_requests: int = 8,
        max_reader_calls: int = 12,
        max_input_tokens: int = 100_000,
        max_output_tokens: int = 16_000,
        model_name: str = DEFAULT_MODEL,
    ) -> None:
        if model_name not in MODEL_NEURON_RATES:
            raise ValueError("Unsupported model neuron rate")
        if not 0 <= daily_neuron_limit <= FREE_DAILY_NEURONS:
            raise ValueError("Daily allowance must fit Workers AI Free allocation")
        if not 1 <= max_owner_daily_neurons <= FREE_DAILY_NEURONS:
            raise ValueError(
                "Owner daily allowance must fit Workers AI Free allocation"
            )
        if (
            min(
                max_active,
                max_model_requests,
                max_reader_calls,
                max_input_tokens,
                max_output_tokens,
            )
            < 1
        ):
            raise ValueError("Quota limits must be positive")
        self.engine = engine
        self.daily_neuron_limit = daily_neuron_limit
        self.max_owner_daily_neurons = max_owner_daily_neurons
        self.max_active = max_active
        self.max_model_requests = max_model_requests
        self.max_reader_calls = max_reader_calls
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.model_name = model_name

    def reserve(
        self,
        task_id: UUID,
        activity_id: str,
        attempt: int,
        kind: str,
        input_tokens: int,
        max_output_tokens: int,
    ) -> QuotaReservation:
        if (
            kind not in {"model", "reader"}
            or not activity_id
            or attempt < 1
            or input_tokens < 0
            or max_output_tokens < 0
            or (kind == "reader" and (input_tokens or max_output_tokens))
        ):
            raise ValueError("Invalid usage attempt")
        if attempt > 1:
            self._retire_prior_attempts(task_id, activity_id, attempt, kind)
        with self.engine.begin() as connection:
            owner = self._lock_task(connection, task_id)
            connection.execute(
                text("SELECT id FROM research_usage_limiter WHERE id=1 FOR UPDATE")
            ).one()
            self._retire_abandoned_slots(connection)
            existing = self._find(connection, task_id, activity_id, attempt, kind)
            if existing is not None:
                if existing.status != "active":
                    raise QuotaError("ATTEMPT_ALREADY_FINISHED")
                return existing
            count = connection.scalar(
                text("""
                SELECT count(*) FROM research_usage_attempts
                WHERE task_id=:task AND kind=:kind
                """),
                dict(task=task_id, kind=kind),
            )
            assert count is not None
            if kind == "model" and count >= self.max_model_requests:
                raise QuotaError("TASK_MODEL_LIMIT")
            if kind == "reader" and count >= self.max_reader_calls:
                raise QuotaError("TASK_READER_LIMIT")
            if kind == "model":
                if self.daily_neuron_limit == 0:
                    raise QuotaError("DAILY_BUDGET_UNCONFIGURED")
                totals = connection.execute(
                    text("""
                    SELECT coalesce(sum(reserved_input_tokens),0),
                           coalesce(sum(reserved_output_tokens),0)
                    FROM research_usage_attempts
                    WHERE task_id=:task AND kind='model'
                    """),
                    dict(task=task_id),
                ).one()
                if totals[0] + input_tokens > self.max_input_tokens:
                    raise QuotaError("TASK_INPUT_TOKEN_LIMIT")
                if totals[1] + max_output_tokens > self.max_output_tokens:
                    raise QuotaError("TASK_OUTPUT_TOKEN_LIMIT")
            active = connection.scalar(
                text("""
                SELECT count(*) FROM research_usage_attempts WHERE status='active'
                """)
            )
            assert active is not None
            if active >= self.max_active:
                raise QuotaError("GLOBAL_CONCURRENCY_LIMIT")
            other_owner_task = connection.scalar(
                text("""
                SELECT 1 FROM research_usage_attempts
                WHERE owner_id=:owner AND task_id<>:task AND status='active'
                LIMIT 1
                """),
                dict(owner=owner, task=task_id),
            )
            if other_owner_task is not None:
                raise QuotaError("OWNER_CONCURRENCY_LIMIT")
            day = connection.scalar(text("SELECT timezone('UTC',now())::date"))
            connection.execute(
                text("""
                INSERT INTO research_usage_days (day_utc) VALUES (:day)
                ON CONFLICT (day_utc) DO NOTHING
                """),
                dict(day=day),
            )
            neurons = (
                reserved_neurons(
                    input_tokens, max_output_tokens, model_name=self.model_name
                )
                if kind == "model"
                else 0
            )
            if kind == "model":
                used = connection.scalar(
                    text("""
                    SELECT reserved_neurons FROM research_usage_days
                    WHERE day_utc=:day FOR UPDATE
                    """),
                    dict(day=day),
                )
                assert used is not None
                if used + neurons > self.daily_neuron_limit:
                    raise QuotaError("DAILY_BUDGET_EXHAUSTED")
                # The singleton limiter lock serializes the owner sum with all
                # model reservations, including those from separate tasks.
                owner_used = connection.scalar(
                    text("""
                    SELECT coalesce(sum(reserved_neurons),0)
                    FROM research_usage_attempts
                    WHERE owner_id=:owner AND day_utc=:day AND kind='model'
                    """),
                    dict(owner=owner, day=day),
                )
                assert owner_used is not None
                if owner_used + neurons > self.max_owner_daily_neurons:
                    raise QuotaError("OWNER_DAILY_BUDGET_EXHAUSTED")
            identifier = uuid4()
            connection.execute(
                text("""
                INSERT INTO research_usage_attempts
                    (id,task_id,owner_id,activity_id,attempt,kind,model_name,status,day_utc,
                     reserved_input_tokens,reserved_output_tokens,reserved_neurons)
                VALUES (:id,:task,:owner,:activity,:attempt,:kind,:model,'active',:day,
                        :input,:output,:neurons)
                """),
                dict(
                    id=identifier,
                    task=task_id,
                    owner=owner,
                    activity=activity_id,
                    attempt=attempt,
                    kind=kind,
                    model=self.model_name if kind == "model" else None,
                    day=day,
                    input=input_tokens,
                    output=max_output_tokens,
                    neurons=neurons,
                ),
            )
            if neurons:
                connection.execute(
                    text("""
                    UPDATE research_usage_days
                    SET reserved_neurons=reserved_neurons+:neurons
                    WHERE day_utc=:day
                    """),
                    dict(day=day, neurons=neurons),
                )
            return QuotaReservation(
                identifier, task_id, activity_id, attempt, kind, "active", neurons
            )

    def _retire_prior_attempts(
        self, task_id: UUID, activity_id: str, attempt: int, kind: str
    ) -> None:
        """Persist a timed-out predecessor even if the new attempt is denied."""
        with self.engine.begin() as connection:
            self._lock_task(connection, task_id)
            connection.execute(
                text("SELECT id FROM research_usage_limiter WHERE id=1 FOR UPDATE")
            ).one()
            connection.execute(
                text("""
                UPDATE research_usage_attempts
                SET status='unknown',finished_at=now()
                WHERE task_id=:task AND activity_id=:activity AND kind=:kind
                  AND attempt<:attempt AND status='active'
                """),
                dict(task=task_id, activity=activity_id, kind=kind, attempt=attempt),
            )

    @staticmethod
    def _retire_abandoned_slots(connection: Connection) -> None:
        """Free slots after a fence or long-abandoned activity, retaining charges."""
        connection.execute(
            text("""
            UPDATE research_usage_attempts u
            SET status='unknown',finished_at=now()
            FROM research_tasks t
            WHERE u.task_id=t.id AND u.status='active'
              AND (
                t.status<>'researching' OR NOT t.write_allowed OR
                u.started_at < now()-interval '10 minutes'
              )
            """)
        )

    def finish(
        self,
        reservation_id: UUID,
        *,
        known: bool,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
    ) -> None:
        if known and (input_tokens is None) != (output_tokens is None):
            raise ValueError("Both token counts must be supplied together")
        if any(
            value is not None and value < 0
            for value in (input_tokens, output_tokens, latency_ms)
        ):
            raise ValueError("Usage counters cannot be negative")
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text("""
                    SELECT * FROM research_usage_attempts WHERE id=:id FOR UPDATE
                    """),
                    dict(id=reservation_id),
                )
                .mappings()
                .one()
            )
            if row["status"] != "active":
                return
            if row["kind"] == "model" and known and input_tokens is None:
                raise ValueError("Known model completion requires provider token usage")
            if known and input_tokens is not None and output_tokens is not None:
                extra_input = max(0, input_tokens - row["reserved_input_tokens"])
                extra_output = max(0, output_tokens - row["reserved_output_tokens"])
                extra_neurons = max(
                    0,
                    reserved_neurons(
                        max(input_tokens, row["reserved_input_tokens"]),
                        max(output_tokens, row["reserved_output_tokens"]),
                        model_name=row["model_name"],
                    )
                    - row["reserved_neurons"],
                )
                if extra_neurons:
                    connection.execute(
                        text("""
                        UPDATE research_usage_days
                        SET reserved_neurons=reserved_neurons+:extra
                        WHERE day_utc=:day
                        """),
                        dict(extra=extra_neurons, day=row["day_utc"]),
                    )
                connection.execute(
                    text("""
                    UPDATE research_usage_attempts
                    SET reserved_input_tokens=reserved_input_tokens+:extra_input,
                        reserved_output_tokens=reserved_output_tokens+:extra_output,
                        reserved_neurons=reserved_neurons+:extra_neurons
                    WHERE id=:id
                    """),
                    dict(
                        id=reservation_id,
                        extra_input=extra_input,
                        extra_output=extra_output,
                        extra_neurons=extra_neurons,
                    ),
                )
            connection.execute(
                text("""
                UPDATE research_usage_attempts
                SET status=:status,actual_input_tokens=:input,
                    actual_output_tokens=:output,latency_ms=:latency,
                    finished_at=now()
                WHERE id=:id
                """),
                dict(
                    id=reservation_id,
                    status="completed" if known else "unknown",
                    input=input_tokens,
                    output=output_tokens,
                    latency=latency_ms,
                ),
            )

    def attempt(self, reservation_id: UUID) -> QuotaReservation:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("""
                    SELECT id,task_id,activity_id,attempt,kind,status,reserved_neurons
                    FROM research_usage_attempts WHERE id=:id
                    """),
                    dict(id=reservation_id),
                )
                .mappings()
                .one()
            )
            return QuotaReservation(**row)

    def daily_reserved_neurons(self) -> int:
        with self.engine.connect() as connection:
            result = connection.scalar(
                text("""
                SELECT coalesce((SELECT reserved_neurons
                                 FROM research_usage_days
                                 WHERE day_utc=timezone('UTC',now())::date),0)
                """)
            )
            assert result is not None
            return result

    @staticmethod
    def _find(
        connection: Connection,
        task_id: UUID,
        activity_id: str,
        attempt: int,
        kind: str,
    ) -> QuotaReservation | None:
        row = (
            connection.execute(
                text("""
                SELECT id,task_id,activity_id,attempt,kind,status,reserved_neurons
                FROM research_usage_attempts
                WHERE task_id=:task AND activity_id=:activity
                  AND attempt=:attempt AND kind=:kind
                """),
                dict(task=task_id, activity=activity_id, attempt=attempt, kind=kind),
            )
            .mappings()
            .first()
        )
        return QuotaReservation(**row) if row is not None else None

    @staticmethod
    def _lock_task(connection: Connection, task_id: UUID) -> UUID:
        preliminary = connection.execute(
            text("""
            SELECT owner_id,plan_id,generation FROM research_tasks WHERE id=:task
            """),
            dict(task=task_id),
        ).first()
        if preliminary is None:
            raise QuotaError("TASK_NOT_FOUND")
        if (
            actor_generation(connection, preliminary.owner_id, lock=True)
            != preliminary.generation
        ):
            raise QuotaError("TASK_NOT_WRITABLE")
        plan = locked_plan(connection, preliminary.plan_id, preliminary.owner_id)
        task = (
            connection.execute(
                text("""
                SELECT status,write_allowed,conditions_revision,generation
                FROM research_tasks WHERE id=:task FOR UPDATE
                """),
                dict(task=task_id),
            )
            .mappings()
            .one()
        )
        if (
            plan is None
            or plan.generation != task["generation"]
            or plan.conditions_revision != task["conditions_revision"]
            or task["status"] != "researching"
            or not task["write_allowed"]
        ):
            raise QuotaError("TASK_NOT_WRITABLE")
        return preliminary.owner_id
