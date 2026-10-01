"""Remove library originals in the caller's fenced control transaction."""

from uuid import UUID

from sqlalchemy import Connection, text

from whisky.modules.discovery.public import locked_plan_deletion_fence
from whisky.modules.identity.public import control_actor_state


def purge_actor_library(connection: Connection, owner: UUID, generation: int) -> None:
    actor = control_actor_state(connection, owner, lock=True)
    if actor is not None and not (
        actor[0] > generation or actor == (generation, False)
    ):
        raise RuntimeError("library purge requires an advanced identity fence")
    for table in (
        "library_commands",
        "library_conclusions",
        "library_bottle_feedback",
        "library_preferences",
    ):
        connection.execute(
            text(
                f"DELETE FROM {table} WHERE owner_id=:owner AND generation<=:generation"
            ),
            dict(owner=owner, generation=generation),
        )


def purge_plan_library(
    connection: Connection, owner: UUID, generation: int, plan_id: UUID
) -> None:
    actor = control_actor_state(connection, owner, lock=True)
    if actor is not None and actor[0] < generation:
        raise RuntimeError("library purge generation is not current")
    if not locked_plan_deletion_fence(connection, plan_id, owner, generation):
        raise RuntimeError("library purge requires a deleted plan fence")
    values = dict(owner=owner, generation=generation, plan=plan_id)
    connection.execute(
        text("""
            DELETE FROM library_commands
            WHERE owner_id=:owner AND generation<=:generation
                AND plan_id=:plan
        """),
        values,
    )
    connection.execute(
        text("""
            DELETE FROM library_conclusions
            WHERE owner_id=:owner AND generation<=:generation AND plan_id=:plan
        """),
        values,
    )
