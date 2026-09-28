"""Absent identity config fails closed; partial config fails startup."""

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    database_url: str
    issuer: str
    audience: str

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
        if not any(items):
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
        return cls(*items)
