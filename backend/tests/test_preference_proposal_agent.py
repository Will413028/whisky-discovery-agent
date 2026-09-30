import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits
from test_proposal_mapping_agent_v4 import reviewed_mapping

from whisky.modules.research.proposal_agent_v4 import preference_proposal_agent_v4
from whisky.modules.research.proposal_context_v4 import ProposalContextV4


def proposal(quote="喜歡甜點"):
    return {
        "summary": "飲食甜香只是待確認線索",
        "preferences": [
            {
                "description": "甜香",
                "intent": "prefer",
                "source_quote": quote,
                "source_kind": "food_clue",
                "certainty": "inferred",
                "strength": "soft",
                "mapping": reviewed_mapping().model_dump(mode="json"),
            }
        ],
    }


async def test_proposal_agent_preserves_food_clue_as_unconfirmed_and_exposes_no_tools():
    def model(messages, info):
        assert not info.function_tools
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, proposal())]
        )

    result = await preference_proposal_agent_v4(FunctionModel(model)).run(
        "原描述：我喜歡甜點",
        deps=ProposalContextV4("我喜歡甜點", (reviewed_mapping(),)),
        usage_limits=UsageLimits(request_limit=2),
    )
    assert result.output.preferences[0].certainty == "inferred"
    assert result.output.preferences[0].strength == "soft"


async def test_invalid_quote_is_retried_once_against_original_description():
    calls = 0

    def model(messages, info):
        nonlocal calls
        calls += 1
        payload = proposal("喝過泥煤酒" if calls == 1 else "喜歡甜點")
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, payload)])

    result = await preference_proposal_agent_v4(FunctionModel(model)).run(
        "原描述：我喜歡甜點",
        deps=ProposalContextV4("我喜歡甜點", (reviewed_mapping(),)),
        usage_limits=UsageLimits(request_limit=2),
    )
    assert calls == 2
    assert result.output.preferences[0].source_quote == "喜歡甜點"


async def test_repeated_fabricated_quotes_fail_without_returning_a_proposal():
    calls = 0

    def model(messages, info):
        nonlocal calls
        calls += 1
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, proposal("不存在的原話"))]
        )

    with pytest.raises(UnexpectedModelBehavior):
        await preference_proposal_agent_v4(FunctionModel(model)).run(
            "原描述：我喜歡甜點",
            deps=ProposalContextV4("我喜歡甜點", (reviewed_mapping(),)),
            usage_limits=UsageLimits(request_limit=2),
        )
    assert calls == 2
