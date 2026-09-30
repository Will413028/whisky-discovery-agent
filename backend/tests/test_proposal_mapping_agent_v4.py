from uuid import UUID

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from whisky.modules.discovery.public import CatalogReference, ReviewedFlavorMapping
from whisky.modules.research.proposal_agent_v4 import preference_proposal_agent_v4
from whisky.modules.research.proposal_context_v4 import ProposalContextV4


def reviewed_mapping():
    return ReviewedFlavorMapping(
        feature_key="fruit",
        reference=CatalogReference(release_id=UUID(int=1), item_id=UUID(int=2)),
        evidence_ids=(UUID(int=3),),
    )


def model_response(mapping, info):
    payload = {
        "summary": "原文仍只是線索",
        "preferences": [
            {
                "description": "可能喜歡果香",
                "intent": "prefer",
                "source_quote": "喜歡水果甜點",
                "source_kind": "food_clue",
                "mapping": mapping.model_dump(mode="json") if mapping else None,
            }
        ],
    }
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, payload)])


async def test_model_uses_only_a_provided_reviewed_anchor_for_an_unconfirmed_clue():
    mapping = reviewed_mapping()
    model = FunctionModel(lambda messages, info: model_response(mapping, info))
    result = await preference_proposal_agent_v4(model).run(
        "我喜歡水果甜點",
        deps=ProposalContextV4("我喜歡水果甜點", (mapping,)),
    )
    assert result.output.preferences[0].mapping == mapping
    assert result.output.preferences[0].certainty == "inferred"


@pytest.mark.parametrize("mapped", [False, True])
async def test_model_cannot_emit_an_unprovided_or_missing_reviewed_mapping(mapped):
    calls = 0

    def model(messages, info):
        nonlocal calls
        calls += 1
        return model_response(reviewed_mapping() if mapped else None, info)

    with pytest.raises(UnexpectedModelBehavior):
        await preference_proposal_agent_v4(FunctionModel(model)).run(
            "我喜歡水果甜點",
            deps=ProposalContextV4("我喜歡水果甜點", ()),
        )
    assert calls == 2
