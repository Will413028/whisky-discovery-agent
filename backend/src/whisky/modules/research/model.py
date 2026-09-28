"""Keep provider reasoning out of durable model activity results."""

from dataclasses import replace

from pydantic_ai.messages import ModelMessage, ModelResponse, ThinkingPart
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings


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
