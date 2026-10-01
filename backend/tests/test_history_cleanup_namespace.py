from types import SimpleNamespace
from uuid import uuid4

import pytest
from temporalio.api.namespace.v1 import NamespaceConfig
from temporalio.service import RPCError, RPCStatusCode

from whisky.modules.research.history_cleanup import TemporalResearchHistoryPurger


class NoActiveHistoryNamespace:
    namespace = "synthetic-namespace"

    def __init__(self, config):
        self.config = config
        self.workflow_service = self

    async def describe_namespace(self, request, **kwargs):
        return SimpleNamespace(config=self.config)

    async def list_workflows(self, *args, **kwargs):
        for value in ():
            yield value

    def get_workflow_handle(self, *args, **kwargs):
        return self

    async def describe(self, **kwargs):
        raise RPCError(
            "synthetic missing active execution", RPCStatusCode.NOT_FOUND, b""
        )


@pytest.mark.parametrize(
    "change",
    [
        {"history_archival_state": 2},
        {"visibility_archival_state": 2},
        {"history_archival_uri": "file:///synthetic-history"},
        {"visibility_archival_uri": "file:///synthetic-visibility"},
        {"history_archival_state": 0},
    ],
)
async def test_active_history_absence_does_not_prove_archived_data_erasure(change):
    config = NamespaceConfig(history_archival_state=1, visibility_archival_state=1)
    for key, value in change.items():
        setattr(config, key, value)
    client = NoActiveHistoryNamespace(config)
    with pytest.raises(ValueError, match="archival"):
        await TemporalResearchHistoryPurger(client).purge(f"whisky-research-{uuid4()}")
