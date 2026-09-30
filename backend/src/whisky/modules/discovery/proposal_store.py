"""Unconfirmed preference snapshots join a caller's fenced transaction."""

from uuid import UUID

from sqlalchemy import Connection, text

from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.proposal import PreferenceProposal
from whisky.modules.discovery.store import Plan


def preference_proposal_for_task(
    connection: Connection,
    task_id: UUID,
    owner_id: UUID,
    generation: int,
    conditions_revision: int,
) -> PreferenceProposal | None:
    payload = connection.scalar(
        text("""
            SELECT proposal FROM preference_proposals
            WHERE task_id=:task AND owner_id=:owner AND generation=:generation
              AND conditions_revision=:revision
        """),
        dict(
            task=task_id,
            owner=owner_id,
            generation=generation,
            revision=conditions_revision,
        ),
    )
    return PreferenceProposal.model_validate(payload) if payload is not None else None


def persist_preference_proposal(
    connection: Connection,
    task_id: UUID,
    plan: Plan,
    source_text: str,
    proposal: PreferenceProposal,
    prompt_version: str,
) -> None:
    """Caller holds identity, plan and task locks; this never edits conditions."""
    proposal.validate_source(source_text)
    existing = (
        connection.execute(
            text("SELECT * FROM preference_proposals WHERE task_id=:task FOR UPDATE"),
            {"task": task_id},
        )
        .mappings()
        .first()
    )
    if existing is not None:
        if (
            existing["plan_id"] != plan.id
            or existing["owner_id"] != plan.owner_id
            or existing["generation"] != plan.generation
            or existing["conditions_revision"] != plan.conditions_revision
            or ResearchConditions.model_validate(existing["base_conditions"])
            != plan.conditions
            or existing["source_text"] != source_text
            or PreferenceProposal.model_validate(existing["proposal"]) != proposal
            or existing["prompt_version"] != prompt_version
        ):
            raise ValueError("PROPOSAL_EXISTS")
        return
    connection.execute(
        text("""
        INSERT INTO preference_proposals
            (task_id,plan_id,owner_id,generation,conditions_revision,base_conditions,
             source_text,proposal,prompt_version)
        VALUES (:task,:plan,:owner,:generation,:revision,CAST(:conditions AS jsonb),
                :source,CAST(:proposal AS jsonb),:prompt)
    """),
        dict(
            task=task_id,
            plan=plan.id,
            owner=plan.owner_id,
            generation=plan.generation,
            revision=plan.conditions_revision,
            conditions=plan.conditions.canonical_json(),
            source=source_text,
            proposal=proposal.model_dump_json(),
            prompt=prompt_version,
        ),
    )
