"""Keep provider reasoning out of durable model activity results."""

import asyncio
import time
from dataclasses import replace
from datetime import timedelta
from typing import cast
from uuid import UUID

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse, ThinkingPart
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings
from temporalio import activity
from temporalio.exceptions import ApplicationError

from whisky.modules.research.quota import QuotaError, QuotaStore

MAX_MODEL_OUTPUT_TOKENS = 2_000
MODEL_INPUT_ENVELOPE_BYTES = 1_024
MAX_PROVIDER_RETRY_DELAY_SECONDS = 30


def _cloudflare_error_code(body: object) -> int | None:
    if isinstance(body, dict):
        code = body.get("code")
        if isinstance(code, int):
            return code
        nested = body.get("error")
        if nested is not None:
            return _cloudflare_error_code(nested)
        errors = body.get("errors")
        if isinstance(errors, list) and errors:
            return _cloudflare_error_code(errors[0])
    return None


class QuotaModel(WrapperModel):
    """Reserve before the provider request and retain unknown charges on failure."""

    def __init__(self, wrapped: Model, quota: QuotaStore) -> None:
        super().__init__(wrapped)
        self.quota = quota

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        info = activity.info()
        workflow_id = info.workflow_id or ""
        prefix = "whisky-research-"
        if not workflow_id.startswith(prefix):
            raise ApplicationError("INVALID_RESEARCH_WORKFLOW", non_retryable=True)
        task_id = UUID(workflow_id.removeprefix(prefix))
        # Include tool/output schemas and a provider-envelope margin; the
        # prompt text alone omits tokens that the provider will bill.
        estimated_input = (
            len(str(messages).encode("utf-8"))
            + len(str(model_request_parameters).encode("utf-8"))
            + MODEL_INPUT_ENVELOPE_BYTES
        )
        try:
            reservation = await asyncio.to_thread(
                self.quota.reserve,
                task_id,
                info.activity_id,
                info.attempt,
                "model",
                estimated_input,
                MAX_MODEL_OUTPUT_TOKENS,
            )
        except QuotaError as error:
            raise ApplicationError(error.code, non_retryable=True) from error
        settings = cast(
            ModelSettings,
            {
                **(model_settings or {}),
                "max_tokens": MAX_MODEL_OUTPUT_TOKENS,
                "parallel_tool_calls": False,
            },
        )
        started = time.monotonic()
        try:
            response = await self.wrapped.request(
                messages, settings, model_request_parameters
            )
        except BaseException as error:
            await asyncio.to_thread(
                self.quota.finish,
                reservation.id,
                known=False,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            if isinstance(error, ModelHTTPError):
                if error.status_code == 429:
                    code = _cloudflare_error_code(error.body)
                    if code == 3040:
                        retry_after = error.retry_after
                        delay = min(
                            retry_after if retry_after is not None else 2,
                            MAX_PROVIDER_RETRY_DELAY_SECONDS,
                        )
                        raise ApplicationError(
                            "MODEL_TEMPORARY_CAPACITY",
                            next_retry_delay=timedelta(seconds=delay),
                        ) from None
                    reason = (
                        "MODEL_DAILY_ALLOCATION_EXHAUSTED"
                        if code == 3036
                        else "MODEL_RATE_LIMIT_UNKNOWN"
                    )
                    raise ApplicationError(reason, non_retryable=True) from None
                if 400 <= error.status_code < 500:
                    raise ApplicationError(
                        f"MODEL_HTTP_{error.status_code}", non_retryable=True
                    ) from None
                raise ApplicationError("MODEL_UPSTREAM_ERROR") from None
            raise
        await asyncio.to_thread(
            self.quota.finish,
            reservation.id,
            known=True,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        return response


class NoThinkingModel(WrapperModel):
    """Only public answer/tool parts may cross the Temporal history boundary."""

    def __init__(self, wrapped: Model) -> None:
        super().__init__(wrapped)

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        response = await self.wrapped.request(
            messages, model_settings, model_request_parameters
        )
        return replace(
            response,
            parts=tuple(
                part for part in response.parts if not isinstance(part, ThinkingPart)
            ),
        )
