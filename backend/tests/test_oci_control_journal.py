"""The OCI adapter must preserve conditional writes and exact pagination."""

from types import SimpleNamespace

import pytest

from whisky.modules.control.journal import ControlJournalConflict
from whisky.modules.control.journal_oci import OciControlJournal


class PreconditionFailed(Exception):
    status = 412


class RetentionBlocked(Exception):
    status = 403
    code = "RetentionRuleViolation"


class FakeObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.requests: list[tuple[str, object]] = []
        self.retained = False

    def put_object(self, namespace, bucket, key, body, *, if_none_match):
        self.requests.append(("put", if_none_match))
        if key in self.objects:
            if self.retained:
                raise RetentionBlocked()
            raise PreconditionFailed()
        self.objects[key] = body

    def get_object(self, namespace, bucket, key, *, range):
        self.requests.append(("read", range))
        return SimpleNamespace(data=SimpleNamespace(content=self.objects[key][:65537]))

    def list_objects(self, namespace, bucket, *, prefix, start, limit):
        self.requests.append(("list", (prefix, start, limit)))
        matches = [
            key
            for key in sorted(self.objects)
            if key.startswith(prefix) and (start is None or key >= start)
        ]
        page = matches[:limit]
        next_start = matches[limit] if len(matches) > limit else None
        return SimpleNamespace(
            data=SimpleNamespace(
                objects=[SimpleNamespace(name=key) for key in page],
                next_start_with=next_start,
            )
        )


def test_create_only_retry_and_conflicting_write():
    client = FakeObjectStorage()
    journal = OciControlJournal(client, "namespace", "controls")
    key = "controls/" + "a" * 32 + "/intent.json"
    journal.put_once(key, b"first")
    journal.put_once(key, b"first")
    with pytest.raises(ControlJournalConflict):
        journal.put_once(key, b"different")
    assert client.objects[key] == b"first"
    assert [value for kind, value in client.requests if kind == "put"] == ["*"] * 3


def test_list_page_passes_start_without_offset_or_time_filter():
    client = FakeObjectStorage()
    journal = OciControlJournal(client, "namespace", "controls")
    client.objects = {
        f"controls/{index:032x}/intent.json": b"data" for index in range(1002)
    }
    first = journal.list_page("controls/", None)
    assert len(first.keys) == 1000
    assert first.next_start is not None
    second = journal.list_page("controls/", first.next_start)
    assert len(second.keys) == 2
    assert second.next_start is None
    assert [value for kind, value in client.requests if kind == "list"] == [
        ("controls/", None, 1000),
        ("controls/", first.next_start, 1000),
    ]


def test_retained_existing_object_allows_only_identical_retry():
    client = FakeObjectStorage()
    client.retained = True
    journal = OciControlJournal(client, "namespace", "controls")
    key = "controls/" + "a" * 32 + "/intent.json"
    journal.put_once(key, b"first")
    journal.put_once(key, b"first")
    with pytest.raises(ControlJournalConflict):
        journal.put_once(key, b"different")
