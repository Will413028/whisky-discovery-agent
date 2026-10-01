"""A complete validated JSON file with bounded in-memory buffering."""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from tempfile import SpooledTemporaryFile
from typing import get_args
from uuid import UUID

from pydantic import TypeAdapter

from whisky.modules.library.export_views import AccountExportDataV1, AccountExportViewV1


@dataclass
class PreparedAccountExport:
    file: SpooledTemporaryFile[bytes]
    size: int
    owner: UUID
    generation: int

    def chunks(self) -> Iterator[bytes]:
        try:
            while chunk := self.file.read(64 * 1024):
                yield chunk
        finally:
            self.file.close()


class ExportFileWriter:
    def __init__(
        self, owner: UUID, generation: int, *, directory: str | None = None
    ) -> None:
        self.owner = owner
        self.generation = generation
        self.adapters = {
            field.alias or name: TypeAdapter(get_args(field.annotation)[0])
            for name, field in AccountExportDataV1.model_fields.items()
        }
        empty = AccountExportDataV1.model_validate({name: [] for name in self.adapters})
        header = AccountExportViewV1(
            owner_id=owner,
            generation=generation,
            exported_at=datetime.now(UTC),
            data=empty,
        ).model_dump(mode="json", by_alias=True, exclude={"data"})
        self.file: SpooledTemporaryFile[bytes] = SpooledTemporaryFile(
            max_size=1024 * 1024, mode="w+b", dir=directory
        )
        self.file.write(json.dumps(header, ensure_ascii=False).encode()[:-1])
        self.file.write(b',"data":{')
        self.seen: set[str] = set()
        self.section: str | None = None
        self.has_row = False

    def append(self, section: str, value: dict) -> None:
        adapter = self.adapters[section]
        row = adapter.validate_python(value)
        encoded = adapter.dump_json(row, by_alias=True)
        if section != self.section:
            if section in self.seen:
                raise ValueError("EXPORT_SECTION_REPEATED")
            if self.section is not None:
                self.file.write(b"],")
            self.file.write(json.dumps(section).encode() + b":[")
            self.section = section
            self.seen.add(section)
            self.has_row = False
        if self.has_row:
            self.file.write(b",")
        self.file.write(encoded)
        self.has_row = True

    def finish(self) -> PreparedAccountExport:
        if self.section is not None:
            self.file.write(b"]")
        for section in self.adapters:
            if section not in self.seen:
                if self.seen:
                    self.file.write(b",")
                self.file.write(json.dumps(section).encode() + b":[]")
                self.seen.add(section)
        self.file.write(b"}}")
        size = self.file.tell()
        self.file.seek(0)
        return PreparedAccountExport(self.file, size, self.owner, self.generation)
