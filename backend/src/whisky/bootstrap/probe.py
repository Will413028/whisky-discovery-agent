"""Infrastructure-only workflow; never represents a research task."""

from temporalio import workflow


@workflow.defn
class BootstrapProbe:
    @workflow.run
    async def run(self) -> str:
        return "ok"
