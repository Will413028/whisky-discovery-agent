"""Persist bounded, unreviewed source text without promoting it to catalog facts."""

from hashlib import sha256
from uuid import uuid4

from sqlalchemy import Engine, text

from whisky.modules.catalog.public import current_release_id, published_source
from whisky.modules.discovery.public import locked_plan
from whisky.modules.identity.public import actor_generation
from whisky.modules.research.contracts import (
    ReadSourceRequest,
    SourceObservation,
    SourceObservationReceipt,
)
from whisky.modules.research.source_reader import SourceReadError, validate_source_url
from whisky.modules.research.store import ResearchConflict


class SourceObservationStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def save(
        self,
        request: ReadSourceRequest,
        activity_id: str,
        observation: SourceObservation,
    ) -> SourceObservationReceipt:
        context = request.context
        selected = request.source
        if (
            not activity_id
            or observation.status not in {"ok", "unavailable"}
            or (observation.status == "ok") != (observation.text is not None)
            or (observation.status == "ok") != (observation.final_url is not None)
            or (observation.status == "unavailable") != (observation.code is not None)
            or (observation.text is not None and len(observation.text) > 2000)
            or (observation.final_url is not None and len(observation.final_url) > 2048)
            or (observation.code is not None and len(observation.code) > 100)
        ):
            raise ValueError("Invalid source observation")
        if observation.final_url is not None:
            try:
                validate_source_url(observation.final_url)
            except SourceReadError as error:
                raise ValueError("Invalid source observation URL") from error
        with self.engine.begin() as connection:
            if (
                actor_generation(connection, context.owner_id, lock=True)
                != context.generation
            ):
                raise ResearchConflict("IDENTITY_CHANGED")
            preliminary = connection.execute(
                text("""
                SELECT plan_id FROM research_tasks
                WHERE id=:task AND owner_id=:owner
                """),
                dict(task=context.task_id, owner=context.owner_id),
            ).first()
            if preliminary is None:
                raise ResearchConflict("NOT_FOUND")
            plan = locked_plan(connection, preliminary.plan_id, context.owner_id)
            task = connection.execute(
                text("""
                SELECT generation,conditions_revision,status,write_allowed
                FROM research_tasks WHERE id=:task AND owner_id=:owner FOR UPDATE
                """),
                dict(task=context.task_id, owner=context.owner_id),
            ).one()
            if (
                plan is None
                or plan.generation != context.generation
                or plan.conditions_revision != context.conditions_revision
                or task.generation != context.generation
                or task.conditions_revision != context.conditions_revision
                or task.status != "researching"
                or not task.write_allowed
            ):
                raise ResearchConflict("TASK_NOT_WRITABLE")
            if current_release_id(connection) != selected.release_id:
                raise ResearchConflict("CATALOG_CHANGED")
            source = published_source(
                connection,
                selected.release_id,
                selected.evidence_id,
                selected.bottle_version_id,
            )
            if source is None:
                raise ResearchConflict("SOURCE_NOT_REVIEWED")
            existing = (
                connection.execute(
                    text("""
                SELECT id,release_id,bottle_version_id,evidence_id,status,error_code,
                       content_sha256,source_checked_on
                FROM research_source_observations
                WHERE task_id=:task AND activity_id=:activity
                """),
                    dict(task=context.task_id, activity=activity_id),
                )
                .mappings()
                .first()
            )
            if existing is not None:
                if (
                    existing["release_id"] != selected.release_id
                    or existing["bottle_version_id"] != selected.bottle_version_id
                    or existing["evidence_id"] != selected.evidence_id
                ):
                    raise ResearchConflict("SOURCE_OBSERVATION_CONFLICT")
                return SourceObservationReceipt(
                    existing["status"],
                    existing["error_code"],
                    existing["id"],
                    existing["content_sha256"],
                    existing["source_checked_on"],
                )
            observation_id = uuid4()
            content_sha256 = (
                sha256(observation.text.encode()).hexdigest()
                if observation.text is not None
                else None
            )
            connection.execute(
                text("""
                INSERT INTO research_source_observations
                    (id,task_id,owner_id,generation,conditions_revision,activity_id,
                     release_id,bottle_version_id,evidence_id,status,error_code,
                     visible_text,effective_url,content_sha256,source_checked_on)
                VALUES (:id,:task,:owner,:generation,:revision,
                        :activity,:release,:bottle,:evidence,:status,:code,
                        :visible,:effective_url,:sha256,:checked)
                """),
                dict(
                    id=observation_id,
                    task=context.task_id,
                    owner=context.owner_id,
                    generation=context.generation,
                    revision=context.conditions_revision,
                    activity=activity_id,
                    release=selected.release_id,
                    bottle=selected.bottle_version_id,
                    evidence=selected.evidence_id,
                    status=observation.status,
                    code=observation.code,
                    visible=observation.text,
                    effective_url=observation.final_url,
                    sha256=content_sha256,
                    checked=source.checked_on,
                ),
            )
            return SourceObservationReceipt(
                observation.status,
                observation.code,
                observation_id,
                content_sha256,
                source.checked_on,
            )
