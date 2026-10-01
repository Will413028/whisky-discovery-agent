import json

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from whisky.modules.research.proposal_agent_v4 import preference_proposal_agent_v4
from whisky.modules.research.proposal_context_v4 import ProposalContextV4


async def test_proposal_uses_validated_json_text_without_provider_output_tools():
    def model(messages, info):
        assert not info.output_tools
        assert not info.function_tools
        return ModelResponse(
            parts=[TextPart(json.dumps({"summary": "尚無明確偏好", "preferences": []}))]
        )

    result = await preference_proposal_agent_v4(FunctionModel(model)).run(
        "不知道口味", deps=ProposalContextV4("不知道口味", ())
    )
    assert result.output.preferences == ()
