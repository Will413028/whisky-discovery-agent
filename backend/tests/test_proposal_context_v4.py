from dataclasses import replace
from uuid import UUID

from whisky.modules.catalog.public import ReviewedFlavorReference
from whisky.modules.discovery.public import CatalogReference
from whisky.modules.research.proposal_context_v4 import proposal_context_v4


def references():
    return (
        ReviewedFlavorReference(UUID(int=1), UUID(int=2), "fruit", (UUID(int=4),)),
        ReviewedFlavorReference(UUID(int=1), UUID(int=2), "unreferenced", ()),
    )


def test_context_uses_only_reviewed_tag_references_without_a_price_dependency():
    context = proposal_context_v4("我喜歡水果", references())
    assert context.source_text == "我喜歡水果"
    assert len(context.mappings) == 1
    mapping = context.mappings[0]
    assert mapping.feature_key == "fruit"
    assert mapping.reference == CatalogReference(
        release_id=UUID(int=1), item_id=UUID(int=2)
    )
    assert mapping.evidence_ids == (UUID(int=4),)


def test_repeated_tags_have_one_stable_reviewed_anchor_in_the_model_context():
    first = references()
    second = replace(first[0], item_id=UUID(int=9))
    context = proposal_context_v4("原文", (*first, second))
    assert len(context.mappings) == 1
    assert context.mappings[0].reference.item_id == UUID(int=2)


def test_an_empty_catalog_cannot_supply_a_fabricated_mapping():
    assert proposal_context_v4("不知道喜歡什麼", ()).mappings == ()


def test_catalog_tags_with_more_than_sixteen_citations_remain_representable():
    evidence_ids = tuple(UUID(int=index) for index in range(10, 27))
    reference = replace(references()[0], evidence_ids=evidence_ids)
    context = proposal_context_v4("原文", (reference,))
    assert context.mappings[0].evidence_ids == evidence_ids
