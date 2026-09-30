"""Trace real source I/O and mark an optional single injected unavailable attempt."""

from temporalio import activity

from whisky.modules.research.source_reader import (
    SourcePage,
    SourceReader,
    SourceReadError,
    validate_source_url,
)


class EvalSourceReader(SourceReader):
    def __init__(self, *, inject_first=False, delegate=None):
        self.inject_first = inject_first
        self.delegate = delegate or SourceReader()
        self.fail_first_workflows: set[str] = set()
        self.calls: dict[str, list[dict[str, object]]] = {}

    async def read(self, url: str) -> SourcePage:
        workflow_id = activity.info().workflow_id
        calls = self.calls.setdefault(workflow_id, [])
        try:
            validate_source_url(url)
        except SourceReadError as error:
            calls.append(
                {
                    "url": url,
                    "status": "unavailable",
                    "code": error.code,
                    "fault_injection": False,
                }
            )
            raise
        if self.inject_first and workflow_id in self.fail_first_workflows and not calls:
            calls.append(
                {
                    "url": url,
                    "status": "unavailable",
                    "code": "SOURCE_HTTP_ERROR",
                    "fault_injection": True,
                }
            )
            raise SourceReadError("SOURCE_HTTP_ERROR")
        try:
            page = await self.delegate.read(url)
        except SourceReadError as error:
            calls.append(
                {
                    "url": url,
                    "status": "unavailable",
                    "code": error.code,
                    "fault_injection": False,
                }
            )
            raise
        calls.append(
            {
                "url": url,
                "status": "ok",
                "final_url": page.final_url,
                "fault_injection": False,
            }
        )
        return page
