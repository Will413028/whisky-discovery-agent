"""PostgreSQL identity mapping; never use an email as an ownership key."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    Engine,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Uuid,
    insert,
    select,
)
from sqlalchemy.exc import IntegrityError

from whisky.modules.identity.tokens import Principal


@dataclass(frozen=True)
class Actor:
    id: UUID
    active: bool


metadata = MetaData()
users = Table(
    "users",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("active", Boolean, nullable=False),
    Column("generation", Integer, nullable=False),
)
identities = Table(
    "identities",
    metadata,
    Column("issuer", String, primary_key=True),
    Column("subject", String, primary_key=True),
    Column("user_id", Uuid, ForeignKey("users.id"), nullable=False),
)


class IdentityStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def read_actor(self, identifier: UUID, owner: UUID) -> Actor | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(users.c.id, users.c.active).where(
                    users.c.id == identifier, users.c.id == owner
                )
            ).first()
            return Actor(row.id, row.active) if row else None

    def resolve(self, principal: Principal) -> Actor | None:
        query = (
            select(users.c.id, users.c.active)
            .join(identities)
            .where(
                identities.c.issuer == principal.issuer,
                identities.c.subject == principal.subject,
            )
        )
        with self.engine.begin() as connection:
            row = connection.execute(query).first()
            if row is None:
                try:
                    with connection.begin_nested():
                        identifier = uuid4()
                        connection.execute(
                            insert(users).values(
                                id=identifier, active=True, generation=1
                            )
                        )
                        connection.execute(
                            insert(identities).values(
                                issuer=principal.issuer,
                                subject=principal.subject,
                                user_id=identifier,
                            )
                        )
                except IntegrityError as error:
                    if getattr(error.orig, "sqlstate", None) != "23505":
                        raise
                row = connection.execute(query).one()
            return Actor(row.id, row.active)
