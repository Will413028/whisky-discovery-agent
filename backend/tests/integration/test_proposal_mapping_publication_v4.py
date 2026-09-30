"""The transaction independently checks a model's reviewed-tag references."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_preference_proposal_publication import prepare

from whisky.modules.catalog.publication import load_reviewed_release
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.research.activities import ResearchActivities
from whisky.modules.research.clarification import ClarificationStore

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("forged", [None, "feature_key", "reference", "evidence_ids"])
def test_reviewed_mapping_is_validated_before_atomic_publication(
    research_context, forged
):
    engine, store, actor, _, context, source, draft = prepare(research_context)
    manifest = Path(__file__).parents[3] / "data/catalog/first-journey.reviewed.json"
    CatalogStore(engine).publish(load_reviewed_release(manifest.read_text()))
    mapping = ResearchActivities(engine)._proposal_mappings_v4()[0]
    if forged == "feature_key":
        mapping = mapping.model_copy(update={"feature_key": "invented-tag"})
    elif forged == "reference":
        mapping = mapping.model_copy(
            update={
                "reference": mapping.reference.model_copy(update={"item_id": uuid4()})
            }
        )
    elif forged == "evidence_ids":
        mapping = mapping.model_copy(update={"evidence_ids": (uuid4(),)})
    draft = draft.model_copy(
        update={
            "preferences": (
                draft.preferences[0].model_copy(update={"mapping": mapping}),
            )
        }
    )
    questions = ClarificationStore(engine)
    if forged is None:
        questions.publish_preference_proposal(
            context, 1, source, draft, datetime.now(UTC) + timedelta(days=7)
        )
        assert store.task(context.task_id, actor.id).status == "needs_input"
        return
    with pytest.raises(ValueError, match="REVIEWED_MAPPING_NOT_FOUND"):
        questions.publish_preference_proposal(
            context, 1, source, draft, datetime.now(UTC) + timedelta(days=7)
        )
    assert store.task(context.task_id, actor.id).status == "researching"
    with engine.connect() as connection:
        for table in ("preference_proposals", "clarifications"):
            assert (
                connection.scalar(
                    text(f"SELECT count(*) FROM {table} WHERE task_id=:task"),
                    {"task": context.task_id},
                )
                == 0
            )
