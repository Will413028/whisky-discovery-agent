"""Public errors omit token contents and infrastructure exceptions."""

from collections.abc import Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from starlette.responses import JSONResponse


class ErrorView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    request_id: UUID
    retryable: bool


def error_response(
    status: int, code: str, request_id: UUID, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        headers=headers,
        content=ErrorView(
            code=code,
            message="服務暫時無法使用，請稍後重試。"
            if status >= 500
            else "無法完成此請求。",
            request_id=request_id,
            retryable=status >= 500,
        ).model_dump(mode="json"),
    )
