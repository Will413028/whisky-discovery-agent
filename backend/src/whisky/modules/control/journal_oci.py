"""OCI Object Storage implementation of the append-only control journal."""

from typing import Any, Protocol, cast

from whisky.modules.control.journal import ControlJournalConflict
from whisky.modules.control.recovery import (
    CONTROL_KEY,
    CONTROL_PREFIX,
    ListingPage,
)


class ObjectClient(Protocol):
    def put_object(
        self, namespace: str, bucket: str, key: str, body: bytes, **kwargs: Any
    ) -> Any: ...

    def get_object(
        self, namespace: str, bucket: str, key: str, **kwargs: Any
    ) -> Any: ...

    def list_objects(self, namespace: str, bucket: str, **kwargs: Any) -> Any: ...


class OciControlJournal:
    """Runtime needs create/read; recovery additionally needs inspect/list."""

    def __init__(self, client: ObjectClient, namespace: str, bucket: str) -> None:
        if not namespace or not bucket:
            raise ValueError("OCI namespace and bucket are required")
        self.client = client
        self.namespace = namespace
        self.bucket = bucket

    @classmethod
    def from_config_file(
        cls, config_file: str, namespace: str, bucket: str
    ) -> "OciControlJournal":
        """Load a project-specific OCI API key; never inherit another app's key."""
        import oci  # type: ignore[import-untyped]

        config = oci.config.from_file(file_location=config_file)
        client = oci.object_storage.ObjectStorageClient(config, timeout=(5, 15))
        return cls(client, namespace, bucket)

    def put_once(self, key: str, body: bytes) -> None:
        if CONTROL_KEY.fullmatch(key) is None:
            raise ValueError("Invalid control object key")
        try:
            self.client.put_object(
                self.namespace,
                self.bucket,
                key,
                body,
                if_none_match="*",
            )
        except Exception as error:
            precondition_failed = getattr(error, "status", None) == 412
            retention_blocked = (
                getattr(error, "status", None) == 403
                and getattr(error, "code", None) == "RetentionRuleViolation"
            )
            if not (precondition_failed or retention_blocked):
                raise
            if self.read(key) != body:
                raise ControlJournalConflict(
                    "External control record already differs"
                ) from error

    def read(self, key: str) -> bytes:
        if CONTROL_KEY.fullmatch(key) is None:
            raise ValueError("Invalid control object key")
        response = self.client.get_object(
            self.namespace,
            self.bucket,
            key,
            range="bytes=0-65536",
        )
        return cast(bytes, response.data.content)

    def list_page(self, prefix: str, start: str | None) -> ListingPage:
        if prefix != CONTROL_PREFIX:
            raise ValueError("Invalid control prefix")
        response = self.client.list_objects(
            self.namespace,
            self.bucket,
            prefix=prefix,
            start=start,
            limit=1000,
        )
        return ListingPage(
            tuple(item.name for item in response.data.objects),
            response.data.next_start_with,
        )
