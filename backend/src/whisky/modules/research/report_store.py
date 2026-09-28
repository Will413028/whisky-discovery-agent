"""Product-owned final research report persistence."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from whisky.modules.catalog.public import (
    PublishedSource,
    current_release_id,
    price_policy_version,
    published_item_name,
    published_price_detail,
    published_source,
    report_candidate_bottle,
    reviewed_version_in_release,
    taiwan_date,
)
from whisky.modules.discovery.public import locked_plan
from whisky.modules.identity.public import actor_generation
from whisky.modules.research.report import ReportDraft
from whisky.modules.research.store import ResearchConflict
from whisky.modules.research.views import (
    ClarifiedBottleView,
    ReportCandidateView,
    ReportClaimView,
    ReportPriceView,
    ReportSourceView,
    ReportView,
)


@dataclass(frozen=True)
class SavedReport:
    id: UUID
    task_id: UUID
    artifact_key: str


def source_view(source: PublishedSource) -> ReportSourceView:
    return ReportSourceView(
        evidence_id=source.id,
        url=source.url,
        publisher=source.publisher,
        checked_on=source.checked_on,
    )


class ReportStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def read(self, owner: UUID, report_id: UUID) -> ReportView | None:
        """Read only the saved snapshot owned by the current actor generation."""
        with self.engine.connect() as connection:
            generation = actor_generation(connection, owner)
            if generation is None:
                return None
            report = (
                connection.execute(
                    text("""
                    SELECT * FROM research_reports
                    WHERE id=:id AND owner_id=:owner AND generation=:generation
                    """),
                    dict(id=report_id, owner=owner, generation=generation),
                )
                .mappings()
                .first()
            )
            if report is None:
                return None
            candidate_rows = connection.execute(
                text("""
                SELECT * FROM research_report_candidates
                WHERE report_id=:report ORDER BY ordinal
                """),
                {"report": report_id},
            ).mappings()
            candidates = []
            for candidate in candidate_rows:
                parameters = dict(report=report_id, ordinal=candidate["ordinal"])
                release_id = candidate["release_id"]
                item_id = candidate["item_id"]
                bottle_id = candidate["bottle_version_id"]
                name = published_item_name(connection, release_id, item_id, bottle_id)
                if name is None:
                    raise RuntimeError("Saved report has an unresolved bottle")
                claim_rows = connection.execute(
                    text("""
                    SELECT * FROM research_report_claims
                    WHERE report_id=:report AND ordinal=:ordinal
                    ORDER BY claim_ordinal
                    """),
                    parameters,
                ).mappings()
                claims = []
                for claim in claim_rows:
                    citations: list[UUID] = list(
                        connection.execute(
                            text("""
                        SELECT evidence_id FROM research_report_citations
                        WHERE report_id=:report AND ordinal=:ordinal
                          AND claim_ordinal=:claim_ordinal
                        ORDER BY evidence_id
                        """),
                            {**parameters, "claim_ordinal": claim["claim_ordinal"]},
                        ).scalars()
                    )
                    sources = []
                    for evidence_id in citations:
                        source = published_source(
                            connection, release_id, evidence_id, bottle_id
                        )
                        if source is None:
                            raise RuntimeError("Saved report has an unresolved source")
                        sources.append(source_view(source))
                    claims.append(
                        ReportClaimView(
                            kind=claim["kind"],
                            key=claim["key"],
                            value=claim["value"],
                            sources=tuple(sources),
                        )
                    )
                price_ids: list[UUID] = list(
                    connection.execute(
                        text("""
                    SELECT price_id FROM research_report_prices
                    WHERE report_id=:report AND ordinal=:ordinal
                    ORDER BY price_id
                    """),
                        parameters,
                    ).scalars()
                )
                prices = []
                for price_id in price_ids:
                    price = published_price_detail(
                        connection, release_id, item_id, bottle_id, price_id
                    )
                    if price is None:
                        raise RuntimeError("Saved report has an unresolved price")
                    prices.append(
                        ReportPriceView(
                            id=price.id,
                            amount=price.amount,
                            currency=price.currency,
                            market=price.market,
                            volume_ml=price.volume_ml,
                            checked_on=price.checked_on,
                            source=source_view(price.source),
                        )
                    )
                candidates.append(
                    ReportCandidateView(
                        release_id=release_id,
                        item_id=item_id,
                        bottle_version_id=bottle_id,
                        name=name,
                        reason=candidate["reason"],
                        claims=tuple(claims),
                        prices=tuple(prices),
                    )
                )
            content = report["content"]
            return ReportView(
                schema_version=report["schema_version"],
                id=report["id"],
                task_id=report["task_id"],
                conditions_revision=report["conditions_revision"],
                catalog_release_id=report["catalog_release_id"],
                evaluated_on=report["evaluated_on"],
                policy_version=report["policy_version"],
                prompt_version=report["prompt_version"],
                model_version=report["model_version"],
                summary=content["summary"],
                unresolved=tuple(content["unresolved"]),
                candidates=tuple(candidates),
                clarified_bottle=(
                    ClarifiedBottleView(
                        question_id=report["clarification_id"],
                        bottle_version_id=report["selected_version_id"],
                        name=report["selected_label"],
                        reviewed_in_release=report["selected_item_id"] is not None,
                    )
                    if report["clarification_id"] is not None
                    else None
                ),
            )

    def save(
        self,
        owner: UUID,
        generation: int,
        task_id: UUID,
        artifact_key: str,
        draft: ReportDraft,
        *,
        policy_version: str,
        prompt_version: str,
        model_version: str,
        clarification_id: UUID | None = None,
        selected_version_id: UUID | None = None,
    ) -> SavedReport:
        versions = (artifact_key, policy_version, prompt_version, model_version)
        if any(not value.strip() or len(value) > 128 for value in versions):
            raise ValueError("Report artifact and versions must be explicit")
        if not draft.summary.strip() or len(draft.summary) > 4000:
            raise ValueError("Report summary must be bounded and nonempty")
        if len(draft.candidates) > 3:
            raise ValueError("A report may include at most three candidates")
        if any(not value.strip() or len(value) > 1000 for value in draft.unresolved):
            raise ValueError("Unresolved questions must be bounded and nonempty")
        with self.engine.begin() as connection:
            if actor_generation(connection, owner, lock=True) != generation:
                raise ResearchConflict("IDENTITY_CHANGED")
            preliminary = connection.execute(
                text(
                    "SELECT plan_id FROM research_tasks "
                    "WHERE id=:task AND owner_id=:owner"
                ),
                dict(task=task_id, owner=owner),
            ).first()
            if preliminary is None:
                raise ResearchConflict("NOT_FOUND")
            plan = locked_plan(connection, preliminary.plan_id, owner)
            if plan is None or plan.generation != generation:
                raise ResearchConflict("NOT_FOUND")
            task = (
                connection.execute(
                    text("""
                SELECT * FROM research_tasks
                WHERE id=:task AND owner_id=:owner FOR UPDATE
                """),
                    dict(task=task_id, owner=owner),
                )
                .mappings()
                .one()
            )
            existing = connection.execute(
                text("""
                SELECT id,artifact_key FROM research_reports
                WHERE task_id=:task AND owner_id=:owner
                """),
                dict(task=task_id, owner=owner),
            ).first()
            if existing is not None:
                if existing.artifact_key != artifact_key:
                    raise ResearchConflict("REPORT_EXISTS")
                return SavedReport(existing.id, task_id, artifact_key)
            if policy_version != price_policy_version():
                raise ResearchConflict("POLICY_CHANGED")
            if (
                task["generation"] != generation
                or plan.conditions_revision != task["conditions_revision"]
                or not task["write_allowed"]
                or task["status"] not in {"acceptance_pending", "queued", "researching"}
            ):
                raise ResearchConflict("TASK_NOT_WRITABLE")
            answered = (
                connection.execute(
                    text("""
                    SELECT id,answer,choices FROM clarifications
                    WHERE task_id=:task AND owner_id=:owner AND status='answered'
                    ORDER BY waiting_version DESC LIMIT 1
                    """),
                    dict(task=task_id, owner=owner),
                )
                .mappings()
                .first()
            )
            if answered is None:
                if clarification_id is not None or selected_version_id is not None:
                    raise ResearchConflict("CLARIFICATION_MISMATCH")
                selected_label = None
            else:
                if (
                    clarification_id != answered["id"]
                    or selected_version_id is None
                    or str(selected_version_id) != answered["answer"]
                ):
                    raise ResearchConflict("CLARIFICATION_MISMATCH")
                selected_label = next(
                    (
                        choice["label"]
                        for choice in answered["choices"]
                        if choice["id"] == answered["answer"]
                    ),
                    None,
                )
                if selected_label is None:
                    raise ResearchConflict("CLARIFICATION_MISMATCH")
            release_ids = {candidate.release_id for candidate in draft.candidates}
            item_refs = {
                (candidate.release_id, candidate.item_id)
                for candidate in draft.candidates
            }
            if len(release_ids) > 1 or len(item_refs) != len(draft.candidates):
                raise ResearchConflict("INVALID_CANDIDATE")
            catalog_release = current_release_id(connection)
            selected_current = (
                reviewed_version_in_release(
                    connection, catalog_release, selected_version_id
                )
                if catalog_release is not None and selected_version_id is not None
                else None
            )
            if selected_version_id is not None and selected_current is None:
                draft = ReportDraft(
                    "所選版本目前不在已覆核酒款資料中，無法確認這個版本。",
                    (),
                    tuple(draft.unresolved)
                    + ("所選版本不在目前 reviewed catalog；請重新核對版本。",),
                )
                release_ids = set()
            if release_ids and release_ids != {catalog_release}:
                raise ResearchConflict("INVALID_CANDIDATE")
            evaluated_on = taiwan_date(datetime.now(UTC))
            verified_candidates = []
            for candidate in draft.candidates:
                if not candidate.reason.strip() or len(candidate.reason) > 2000:
                    raise ResearchConflict("INVALID_CANDIDATE")
                verified = report_candidate_bottle(
                    connection,
                    candidate.release_id,
                    candidate.item_id,
                    tuple(
                        (claim.kind, claim.key, claim.value, claim.evidence_ids)
                        for claim in candidate.claims
                    ),
                    plan.conditions.budget_twd,
                    evaluated_on,
                )
                if (
                    verified is None
                    or set(candidate.price_ids) != set(verified.price_ids)
                    or len(candidate.price_ids) != len(verified.price_ids)
                ):
                    raise ResearchConflict("INVALID_CANDIDATE")
                verified_candidates.append(verified)
            report_id = uuid4()
            connection.execute(
                text("""
                INSERT INTO research_reports
                    (id,task_id,owner_id,generation,conditions_revision,
                     artifact_key,catalog_release_id,evaluated_on,policy_version,
                     prompt_version,model_version,schema_version,content,
                     clarification_id,selected_version_id,selected_label,selected_item_id)
                VALUES (:id,:task,:owner,:generation,:revision,:key,:release,:evaluated,
                        :policy,:prompt,:model,1,CAST(:content AS jsonb),
                        :clarification,:selected_version,:selected_label,:selected_item)
                """),
                dict(
                    id=report_id,
                    task=task_id,
                    owner=owner,
                    generation=generation,
                    revision=task["conditions_revision"],
                    key=artifact_key,
                    release=catalog_release,
                    evaluated=evaluated_on,
                    policy=policy_version,
                    prompt=prompt_version,
                    model=model_version,
                    clarification=clarification_id,
                    selected_version=selected_version_id,
                    selected_label=selected_current.name
                    if selected_current
                    else selected_label,
                    selected_item=selected_current.item_id
                    if selected_current
                    else None,
                    content=json.dumps(
                        dict(summary=draft.summary, unresolved=draft.unresolved),
                        ensure_ascii=False,
                    ),
                ),
            )
            for ordinal, (candidate, verified) in enumerate(
                zip(draft.candidates, verified_candidates, strict=True)
            ):
                connection.execute(
                    text("""
                    INSERT INTO research_report_candidates
                        (report_id,ordinal,release_id,item_id,bottle_version_id,reason)
                    VALUES (:report,:ordinal,:release,:item,:bottle,:reason)
                    """),
                    dict(
                        report=report_id,
                        ordinal=ordinal,
                        release=candidate.release_id,
                        item=candidate.item_id,
                        bottle=verified.bottle_version_id,
                        reason=candidate.reason,
                    ),
                )
                for claim_ordinal, claim in enumerate(candidate.claims):
                    references = dict(
                        report=report_id,
                        ordinal=ordinal,
                        claim_ordinal=claim_ordinal,
                        release=candidate.release_id,
                        item=candidate.item_id,
                        bottle=verified.bottle_version_id,
                        kind=claim.kind,
                        key=claim.key,
                    )
                    connection.execute(
                        text("""
                        INSERT INTO research_report_claims
                            (report_id,ordinal,claim_ordinal,release_id,item_id,
                             bottle_version_id,kind,key,value)
                        VALUES (:report,:ordinal,:claim_ordinal,:release,:item,
                                :bottle,:kind,:key,:value)
                        """),
                        {**references, "value": claim.value},
                    )
                    for evidence_id in claim.evidence_ids:
                        connection.execute(
                            text("""
                            INSERT INTO research_report_citations
                                (report_id,ordinal,claim_ordinal,release_id,item_id,
                                 bottle_version_id,kind,key,evidence_id)
                            VALUES (:report,:ordinal,:claim_ordinal,:release,:item,
                                    :bottle,:kind,:key,:evidence)
                            """),
                            {**references, "evidence": evidence_id},
                        )
                for price_id in verified.price_ids:
                    connection.execute(
                        text("""
                        INSERT INTO research_report_prices
                            (report_id,ordinal,release_id,item_id,
                             bottle_version_id,price_id)
                        VALUES (:report,:ordinal,:release,:item,:bottle,:price)
                        """),
                        dict(
                            report=report_id,
                            ordinal=ordinal,
                            release=candidate.release_id,
                            item=candidate.item_id,
                            bottle=verified.bottle_version_id,
                            price=price_id,
                        ),
                    )
            changed = connection.execute(
                text("""
                UPDATE research_tasks
                SET status='completed',stage='研究完成',report_id=:report,
                    view_version=view_version+1,updated_at=now()
                WHERE id=:task AND owner_id=:owner AND generation=:generation
                  AND conditions_revision=:revision AND write_allowed
                  AND status IN ('acceptance_pending','queued','researching')
                RETURNING id
                """),
                dict(
                    report=report_id,
                    task=task_id,
                    owner=owner,
                    generation=generation,
                    revision=task["conditions_revision"],
                ),
            ).scalar()
            if changed is None:
                raise ResearchConflict("TASK_NOT_WRITABLE")
            connection.execute(
                text("""
                UPDATE agent_turns SET outcome=CAST(:outcome AS jsonb)
                WHERE task_id=:task AND owner_id=:owner AND outcome IS NULL
                """),
                dict(
                    task=task_id,
                    owner=owner,
                    outcome=json.dumps({"type": "success", "reportId": str(report_id)}),
                ),
            )
            return SavedReport(report_id, task_id, artifact_key)
