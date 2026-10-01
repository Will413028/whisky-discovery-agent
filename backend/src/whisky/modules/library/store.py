"""Transactional saving of conclusions from completed, owned reports."""

import json
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, text

from whisky.modules.catalog import public as catalog
from whisky.modules.discovery.public import locked_plan, owned_plan
from whisky.modules.identity.public import actor_generation
from whisky.modules.library.contracts import (
    BottleFeedbackViewV1,
    ConclusionContextViewV1,
    ConclusionRevisitViewV1,
    ConclusionViewV1,
    RevisitedVersionV1,
    RevisitPriceV1,
    SaveBottleFeedbackV1,
    SaveConclusionV1,
)
from whisky.modules.library.domain import exploration_choice
from whisky.modules.research.public import concludable_report


class LibraryConflict(ValueError):
    pass


@dataclass(frozen=True)
class ConclusionCursor:
    updated_at: datetime
    id: UUID


@dataclass(frozen=True)
class ConclusionPage:
    items: tuple[ConclusionViewV1, ...]
    next_cursor: ConclusionCursor | None


@dataclass(frozen=True)
class FeedbackPage:
    items: tuple[BottleFeedbackViewV1, ...]
    next_cursor: ConclusionCursor | None


class LibraryStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def page_bottle_feedback(
        self, owner: UUID, limit: int = 20, cursor: ConclusionCursor | None = None
    ) -> FeedbackPage:
        if not 1 <= limit <= 50:
            raise ValueError("INVALID_PAGE_LIMIT")
        with self.engine.connect() as connection:
            generation = actor_generation(connection, owner)
            if generation is None:
                return FeedbackPage((), None)
            after = "AND (updated_at,id)<(:at,:id)" if cursor is not None else ""
            parameters = dict(owner=owner, generation=generation, count=limit + 1)
            if cursor is not None:
                parameters.update(at=cursor.updated_at, id=cursor.id)
            rows = (
                connection.execute(
                    text(f"""
                SELECT * FROM library_bottle_feedback
                WHERE owner_id=:owner AND generation=:generation
                    AND (want_to_explore OR tasting<>'not_tasted') {after}
                ORDER BY updated_at DESC,id DESC LIMIT :count
            """),
                    parameters,
                )
                .mappings()
                .all()
            )
            visible = rows[:limit]
            return FeedbackPage(
                tuple(self._feedback_view(row) for row in visible),
                ConclusionCursor(visible[-1]["updated_at"], visible[-1]["id"])
                if len(rows) > limit
                else None,
            )

    def read_bottle_feedback(
        self, owner: UUID, version: UUID
    ) -> BottleFeedbackViewV1 | None:
        with self.engine.connect() as connection:
            generation = actor_generation(connection, owner)
            if generation is None:
                return None
            row = (
                connection.execute(
                    text("""
                SELECT * FROM library_bottle_feedback
                WHERE owner_id=:owner AND generation=:generation
                    AND bottle_version_id=:version
            """),
                    dict(owner=owner, generation=generation, version=version),
                )
                .mappings()
                .first()
            )
            return self._feedback_view(row) if row is not None else None

    def save_bottle_feedback(
        self, owner: UUID, generation: int, command: SaveBottleFeedbackV1
    ) -> BottleFeedbackViewV1:
        digest = sha256(
            json.dumps(
                command.model_dump(mode="json", by_alias=True),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        with self.engine.begin() as connection:
            if actor_generation(connection, owner, lock=True) != generation:
                raise LibraryConflict("IDENTITY_CHANGED")
            prior = connection.execute(
                text("""
                SELECT payload_hash,target_id,response FROM library_commands
                WHERE owner_id=:owner AND generation=:generation
                    AND scope='feedback.save' AND key=:key
            """),
                dict(owner=owner, generation=generation, key=command.key),
            ).first()
            if prior is not None:
                if prior.payload_hash != digest:
                    raise LibraryConflict("IDEMPOTENCY_CONFLICT")
                visible = connection.scalar(
                    text("""
                    SELECT id FROM library_bottle_feedback
                    WHERE id=:id AND owner_id=:owner AND generation=:generation
                """),
                    dict(id=prior.target_id, owner=owner, generation=generation),
                )
                if visible is None:
                    raise LibraryConflict("NOT_FOUND")
                return BottleFeedbackViewV1.model_validate(prior.response)
            existing = (
                connection.execute(
                    text("""
                SELECT * FROM library_bottle_feedback
                WHERE owner_id=:owner AND generation=:generation
                    AND bottle_version_id=:version
            """),
                    dict(
                        owner=owner,
                        generation=generation,
                        version=command.bottle_version_id,
                    ),
                )
                .mappings()
                .first()
            )
            if command.expected_revision != (existing["revision"] if existing else 0):
                raise LibraryConflict("REVISION_CONFLICT")
            if existing is None:
                release_id = catalog.current_release_id(connection)
                if (
                    release_id is None
                    or catalog.reviewed_version_in_release(
                        connection, release_id, command.bottle_version_id
                    )
                    is None
                ):
                    raise LibraryConflict("UNKNOWN_BOTTLE_VERSION")
                row = (
                    connection.execute(
                        text("""
                    INSERT INTO library_bottle_feedback
                        (id,owner_id,generation,bottle_version_id,revision,
                         want_to_explore,tasting,tasting_reason)
                    VALUES (:id,:owner,:generation,:version,1,:want,:tasting,:reason)
                    RETURNING *
                """),
                        dict(
                            id=uuid4(),
                            owner=owner,
                            generation=generation,
                            version=command.bottle_version_id,
                            want=command.want_to_explore,
                            tasting=command.tasting,
                            reason=command.tasting_reason,
                        ),
                    )
                    .mappings()
                    .one()
                )
            else:
                row = (
                    connection.execute(
                        text("""
                    UPDATE library_bottle_feedback
                    SET revision=revision+1,want_to_explore=:want,tasting=:tasting,
                        tasting_reason=:reason,updated_at=now()
                    WHERE id=:id RETURNING *
                """),
                        dict(
                            id=existing["id"],
                            want=command.want_to_explore,
                            tasting=command.tasting,
                            reason=command.tasting_reason,
                        ),
                    )
                    .mappings()
                    .one()
                )
            saved = self._feedback_view(row)
            connection.execute(
                text("""
                INSERT INTO library_commands
                    (id,owner_id,generation,scope,key,payload_hash,target_id,response)
                VALUES (:id,:owner,:generation,'feedback.save',:key,:hash,
                    :target,CAST(:response AS jsonb))
            """),
                dict(
                    id=uuid4(),
                    owner=owner,
                    generation=generation,
                    key=command.key,
                    hash=digest,
                    target=saved.id,
                    response=saved.model_dump_json(by_alias=True),
                ),
            )
            return saved

    @staticmethod
    def _feedback_view(row: RowMapping) -> BottleFeedbackViewV1:
        return BottleFeedbackViewV1(
            id=row["id"],
            bottle_version_id=row["bottle_version_id"],
            revision=row["revision"],
            want_to_explore=row["want_to_explore"],
            tasting=row["tasting"],
            tasting_reason=row["tasting_reason"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def revisit_conclusion(
        self, owner: UUID, identifier: UUID, as_of: date
    ) -> ConclusionRevisitViewV1 | None:
        with self.engine.connect() as connection:
            generation = actor_generation(connection, owner)
            if generation is None:
                return None
            row = self._visible_row(connection, owner, generation, identifier)
            if row is None:
                return None
            saved = self._view(row)
            release_id = catalog.current_release_id(connection)
            versions = (
                *((saved.selected_version_id,) if saved.selected_version_id else ()),
                *saved.alternative_version_ids,
            )
            candidates = {
                candidate.item.bottle.version_id: candidate
                for candidate in catalog.reviewed_candidates_for_versions(
                    connection, release_id, versions, as_of
                )
            }
            items = []
            for version in versions:
                candidate = candidates.get(version)
                upper = candidate.price_upper_bound if candidate else None
                budget = saved.conditions.budget_twd
                prices = []
                if candidate is not None:
                    for price in candidate.prices:
                        detail = catalog.published_price_detail(
                            connection=connection,
                            release_id=candidate.release_id,
                            item_id=candidate.item.id,
                            bottle_version_id=version,
                            price_id=price.id,
                        )
                        if (
                            detail is None
                            or detail.amount is None
                            or detail.checked_on is None
                            or detail.volume_ml is None
                        ):
                            raise LibraryConflict("CATALOG_UNAVAILABLE")
                        prices.append(
                            RevisitPriceV1(
                                id=detail.id,
                                amount=detail.amount,
                                volume_ml=detail.volume_ml,
                                checked_on=detail.checked_on,
                                source_url=detail.source.url,
                            )
                        )
                items.append(
                    RevisitedVersionV1(
                        bottle_version_id=version,
                        availability="resolved" if candidate else "unresolved",
                        name=candidate.item.name if candidate else None,
                        price_upper_bound_twd=upper,
                        price_qualification="qualified"
                        if upper is not None
                        else "unqualified",
                        budget_qualification="not_filtered"
                        if budget is None
                        else "unknown"
                        if upper is None
                        else "within_budget"
                        if catalog.fits_budget(upper, budget)
                        else "over_budget",
                        prices=tuple(prices),
                    )
                )
            return ConclusionRevisitViewV1(
                conclusion_id=saved.id,
                plan_id=saved.plan_id,
                conditions_revision=saved.conditions_revision,
                evaluated_on=as_of,
                catalog_release_id=release_id,
                price_policy_version=catalog.price_policy_version(),
                budget_twd=saved.conditions.budget_twd,
                items=tuple(items),
            )

    def conclusion_context(
        self, owner: UUID, report_id: UUID
    ) -> ConclusionContextViewV1 | None:
        with self.engine.connect() as connection:
            generation = actor_generation(connection, owner)
            if generation is None:
                return None
            source = concludable_report(connection, owner, generation, None, report_id)
            if source is None:
                return None
            plan = owned_plan(connection, source.plan_id, owner)
            if plan is None or plan.generation != generation:
                return None
            return ConclusionContextViewV1(
                plan_id=source.plan_id,
                task_id=source.task_id,
                report_id=source.id,
                conditions_revision=source.conditions_revision,
                current_conditions_revision=plan.conditions_revision,
            )

    def page_conclusions(
        self,
        owner: UUID,
        plan_id: UUID,
        limit: int = 20,
        cursor: ConclusionCursor | None = None,
    ) -> ConclusionPage:
        if not 1 <= limit <= 50:
            raise ValueError("Page limit must be between 1 and 50")
        if cursor is not None and cursor.updated_at.utcoffset() is None:
            raise ValueError("Page cursor requires a timezone-aware timestamp")
        after = "AND (updated_at,id)<(:time,:cursor_id)" if cursor else ""
        with self.engine.connect() as connection:
            generation = actor_generation(connection, owner)
            plan = owned_plan(connection, plan_id, owner)
            if generation is None or plan is None or plan.generation != generation:
                raise LibraryConflict("NOT_FOUND")
            rows = (
                connection.execute(
                    text(
                        """
                SELECT * FROM library_conclusions
                WHERE owner_id=:owner AND generation=:generation AND plan_id=:plan
                    AND deleted_at IS NULL
            """
                        + after
                        + " ORDER BY updated_at DESC,id DESC LIMIT :limit"
                    ),
                    dict(
                        owner=owner,
                        generation=generation,
                        plan=plan_id,
                        limit=limit + 1,
                        time=cursor.updated_at if cursor else None,
                        cursor_id=cursor.id if cursor else None,
                    ),
                )
                .mappings()
                .all()
            )
        visible = rows[:limit]
        return ConclusionPage(
            tuple(self._view(row) for row in visible),
            ConclusionCursor(visible[-1]["updated_at"], visible[-1]["id"])
            if len(rows) > limit
            else None,
        )

    def read_conclusion(self, owner: UUID, identifier: UUID) -> ConclusionViewV1 | None:
        with self.engine.connect() as connection:
            generation = actor_generation(connection, owner)
            if generation is None:
                return None
            row = self._visible_row(connection, owner, generation, identifier)
            return self._view(row) if row is not None else None

    @staticmethod
    def _visible_row(
        connection: Connection, owner: UUID, generation: int, identifier: UUID
    ) -> RowMapping | None:
        row = (
            connection.execute(
                text("""
            SELECT * FROM library_conclusions
            WHERE id=:id AND owner_id=:owner AND generation=:generation
                AND deleted_at IS NULL
        """),
                dict(id=identifier, owner=owner, generation=generation),
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        plan = owned_plan(connection, row["plan_id"], owner)
        return row if plan is not None and plan.generation == generation else None

    @staticmethod
    def _view(row: RowMapping) -> ConclusionViewV1:
        content = row["content"]
        return ConclusionViewV1(
            id=row["id"],
            plan_id=row["plan_id"],
            task_id=row["task_id"],
            report_id=row["report_id"],
            conditions_revision=row["conditions_revision"],
            conditions=row["conditions"],
            catalog_release_id=row["catalog_release_id"],
            evaluated_on=row["evaluated_on"],
            revision=row["revision"],
            outcome=content["outcome"],
            selected_version_id=content["selected_version_id"],
            selected_bottle_name=content["selected_bottle_name"],
            alternative_version_ids=content["alternative_version_ids"],
            reason=content["reason"],
            tradeoff=content["tradeoff"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save_conclusion(
        self, owner: UUID, generation: int, command: SaveConclusionV1
    ) -> ConclusionViewV1:
        digest = sha256(
            json.dumps(
                command.model_dump(mode="json", by_alias=True),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        with self.engine.begin() as connection:
            if actor_generation(connection, owner, lock=True) != generation:
                raise LibraryConflict("IDENTITY_CHANGED")
            plan = locked_plan(connection, command.plan_id, owner)
            if plan is None or plan.generation != generation:
                raise LibraryConflict("NOT_FOUND")
            prior = connection.execute(
                text("""
                SELECT payload_hash,target_id,response FROM library_commands
                WHERE owner_id=:owner AND generation=:generation
                    AND scope='conclusions.save' AND key=:key
            """),
                dict(owner=owner, generation=generation, key=command.key),
            ).first()
            if prior is not None:
                if prior.payload_hash != digest:
                    raise LibraryConflict("IDEMPOTENCY_CONFLICT")
                if (
                    self._visible_row(connection, owner, generation, prior.target_id)
                    is None
                ):
                    raise LibraryConflict("NOT_FOUND")
                return ConclusionViewV1.model_validate(prior.response)
            if plan.conditions_revision != command.expected_conditions_revision:
                raise LibraryConflict("REVISION_CONFLICT")
            source = concludable_report(
                connection, owner, generation, plan.id, command.report_id
            )
            if source is None:
                raise LibraryConflict("NOT_FOUND")
            if source.conditions_revision != command.expected_conditions_revision:
                raise LibraryConflict("REVISION_CONFLICT")
            try:
                choice = exploration_choice(
                    source.candidate_version_ids,
                    command.selected_version_id,
                    command.reason,
                    command.tradeoff,
                )
            except ValueError as error:
                raise LibraryConflict(str(error)) from None
            identifier = uuid4()
            selected_name = next(
                (
                    candidate.name
                    for candidate in source.candidates
                    if candidate.version_id == choice.selected_version_id
                ),
                None,
            )
            content = json.dumps(
                dict(
                    schemaVersion=1,
                    outcome=choice.outcome,
                    selected_version_id=str(choice.selected_version_id)
                    if choice.selected_version_id
                    else None,
                    selected_bottle_name=selected_name,
                    alternative_version_ids=[
                        str(version) for version in choice.alternative_version_ids
                    ],
                    reason=choice.reason,
                    tradeoff=choice.tradeoff,
                )
            )
            row = connection.execute(
                text("""
                INSERT INTO library_conclusions
                    (id,owner_id,generation,plan_id,task_id,report_id,
                     conditions_revision,conditions,catalog_release_id,evaluated_on,content)
                VALUES (:id,:owner,:generation,:plan,:task,:report,:revision,
                    CAST(:conditions AS jsonb),:release,:evaluated,
                    CAST(:content AS jsonb))
                RETURNING created_at,updated_at
            """),
                dict(
                    id=identifier,
                    owner=owner,
                    generation=generation,
                    plan=plan.id,
                    task=source.task_id,
                    report=source.id,
                    revision=source.conditions_revision,
                    conditions=source.conditions.canonical_json(),
                    release=source.catalog_release_id,
                    evaluated=source.evaluated_on,
                    content=content,
                ),
            ).one()
            saved = ConclusionViewV1(
                id=identifier,
                plan_id=plan.id,
                task_id=source.task_id,
                report_id=source.id,
                conditions_revision=source.conditions_revision,
                conditions=source.conditions,
                catalog_release_id=source.catalog_release_id,
                evaluated_on=source.evaluated_on,
                revision=1,
                outcome=choice.outcome,
                selected_version_id=choice.selected_version_id,
                selected_bottle_name=selected_name,
                alternative_version_ids=choice.alternative_version_ids,
                reason=choice.reason,
                tradeoff=choice.tradeoff,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            connection.execute(
                text("""
                INSERT INTO library_commands
                    (id,owner_id,generation,scope,key,payload_hash,target_id,response)
                VALUES (:id,:owner,:generation,'conclusions.save',:key,:hash,
                    :target,CAST(:response AS jsonb))
            """),
                dict(
                    id=uuid4(),
                    owner=owner,
                    generation=generation,
                    key=command.key,
                    hash=digest,
                    target=identifier,
                    response=saved.model_dump_json(by_alias=True),
                ),
            )
            return saved
