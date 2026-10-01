import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from whisky.modules.library.export_file import ExportFileWriter
from whisky.modules.library.export_views import AccountExportViewV1


def test_complete_file_preserves_empty_sections_and_closes_after_download(tmp_path):
    owner = uuid4()
    writer = ExportFileWriter(owner, 1, directory=str(tmp_path))
    for _ in range(4):
        writer.append(
            "researchInputs",
            dict(
                task_id=str(uuid4()),
                input={"synthetic": "x" * (512 * 1024)},
                source_task_id=None,
            ),
        )
    prepared = writer.finish()
    assert prepared.size > 1024 * 1024
    chunks = list(prepared.chunks())
    assert all(len(chunk) <= 64 * 1024 for chunk in chunks)
    value = AccountExportViewV1.model_validate_json(b"".join(chunks))
    assert value.owner_id == owner
    assert len(value.data.research_inputs) == 4
    assert value.data.plans == ()
    assert prepared.file.closed
    assert list(tmp_path.iterdir()) == []


def test_interrupted_download_closes_anonymous_file(tmp_path):
    writer = ExportFileWriter(uuid4(), 1, directory=str(tmp_path))
    prepared = writer.finish()
    chunks = prepared.chunks()
    assert json.loads(next(chunks))["schemaVersion"] == 1
    chunks.close()
    assert prepared.file.closed
    assert list(tmp_path.iterdir()) == []


def test_bad_record_or_repeated_section_is_never_silently_serialized():
    writer = ExportFileWriter(uuid4(), 1)
    try:
        with pytest.raises(ValidationError):
            writer.append("researchInputs", {"unexpected": True})
        row = dict(task_id=str(uuid4()), input={}, source_task_id=None)
        writer.append("researchInputs", row)
        writer.append(
            "preferences",
            dict(revision=1, preferences=[], updated_at="2026-10-01T00:00:00Z"),
        )
        with pytest.raises(ValueError, match="EXPORT_SECTION_REPEATED"):
            writer.append("researchInputs", row)
    finally:
        writer.file.close()
