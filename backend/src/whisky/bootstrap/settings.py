"""Absent identity config fails closed; partial config fails startup."""

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class TemporalSettings:
    address: str
    namespace: str
    task_queue: str

    def __post_init__(self) -> None:
        target = urlsplit("//" + self.address)
        if (
            not target.hostname
            or target.port is None
            or target.port == 0
            or target.username
            or target.password
            or target.path
            or target.query
            or target.fragment
            or len(self.address) > 512
            or any(char.isspace() for char in self.address)
        ):
            raise ValueError("Temporal address requires host:port without credentials")
        for value in (self.namespace, self.task_queue):
            if not 1 <= len(value) <= 255 or any(char.isspace() for char in value):
                raise ValueError(
                    "Temporal namespace and task queue must be explicit names"
                )


@dataclass(frozen=True)
class Settings:
    database_url: str
    issuer: str
    audience: str
    temporal: TemporalSettings | None = None

    @classmethod
    def from_environment(cls, values: Mapping[str, str]) -> "Settings | None":
        items = [
            values.get(name, "")
            for name in (
                "WHISKY_DATABASE_URL",
                "WHISKY_AUTH0_ISSUER",
                "WHISKY_AUTH0_AUDIENCE",
            )
        ]
        temporal_items = [
            values.get(name, "")
            for name in (
                "WHISKY_TEMPORAL_ADDRESS",
                "WHISKY_TEMPORAL_NAMESPACE",
                "WHISKY_TEMPORAL_TASK_QUEUE",
            )
        ]
        if not any(items) and not any(temporal_items):
            return None
        if not all(items):
            raise ValueError("All identity configuration values are required")
        issuer = urlsplit(items[1])
        if (
            issuer.scheme != "https"
            or not issuer.hostname
            or issuer.username
            or issuer.password
            or issuer.path != "/"
            or issuer.query
            or issuer.fragment
        ):
            raise ValueError("Auth0 issuer must be an HTTPS origin ending in /")
        if not items[0].startswith("postgresql+psycopg://"):
            raise ValueError("Identity storage requires PostgreSQL with psycopg")
        temporal = None
        if any(temporal_items):
            if not all(temporal_items):
                raise ValueError("All Temporal configuration values are required")
            temporal = TemporalSettings(*temporal_items)
        return cls(items[0], items[1], items[2], temporal=temporal)
