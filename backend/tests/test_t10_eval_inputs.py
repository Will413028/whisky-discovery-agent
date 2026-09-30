import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location(
    "whisky_t10_eval_inputs", ROOT / "backend/evals/t10_inputs.py"
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixtures():
    return json.loads(
        (ROOT / "backend/evals/t10_cases.v1.json").read_text()
    ), json.loads((ROOT / "backend/evals/t10_inputs.v1.json").read_text())


def test_every_frozen_case_has_one_legal_typed_fixture_and_keeps_raw_proposal_text():
    corpus, controls = fixtures()
    values = module.validated_cases(corpus, controls)
    assert len(values) == 13
    for case in corpus["cases"]:
        conditions, request = values[case["id"]]
        assert conditions.goal == case["input"]
        assert request.source_text == (
            case["input"] if request.phase == "proposal" else None
        )
    assert values["expert_generic_name"][1].intent.origin_query == "格蘭菲迪"
    assert values["expert_explicit_origin"][1].intent.explore_feature == "太妃糖"
    assert values["hard_smoke_comparison"][0].preferences[0].strength == "hard"


@pytest.mark.parametrize(
    "mutation", ["missing", "extra", "wrong_version", "changed_quote"]
)
def test_controls_cannot_silently_skip_cases_or_rewrite_the_frozen_proposal(mutation):
    corpus, controls = fixtures()
    controls = deepcopy(controls)
    if mutation == "missing":
        controls["cases"].pop("beginner_unknown")
    elif mutation == "extra":
        controls["cases"]["unplanned"] = {}
    elif mutation == "wrong_version":
        controls["corpus_version"] = 99
    else:
        controls["cases"]["beginner_unknown"]["input"]["sourceText"] = "事後改題"
    with pytest.raises(ValueError, match="EVAL_INPUT"):
        module.validated_cases(corpus, controls)


@pytest.mark.parametrize("stop", [False, True])
def test_proposal_reply_uses_the_known_command_choice_or_stops_for_confirmation(stop):
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4, uuid5

    from whisky.modules.research.views import QuestionView

    task = uuid4()
    choice = uuid5(task, "proposal:use-intent")
    question = QuestionView(
        id=uuid4(),
        prompt="確認",
        waitingVersion=1,
        expiresAt=datetime.now(UTC) + timedelta(days=7),
        choices=[{"id": choice, "label": "只使用方向"}],
    )
    corpus, raw = fixtures()
    control = module.CaseControls.model_validate(raw["cases"]["beginner_unknown"])
    if stop:
        control = control.model_copy(update={"stop_at": "proposal_question"})
    assert module.select_answer(task, question, True, control) == (
        None if stop else choice
    )


def test_version_reply_requires_one_explicit_match_without_arbitrary_fallback():
    from datetime import UTC, datetime, timedelta
    from uuid import UUID, uuid4

    from whisky.modules.research.views import QuestionView

    task = uuid4()
    corpus, raw = fixtures()
    control = module.CaseControls.model_validate(raw["cases"]["expert_generic_name"])
    choice = UUID(str(control.version_choice))
    question = QuestionView(
        id=uuid4(),
        prompt="版本",
        waitingVersion=1,
        expiresAt=datetime.now(UTC) + timedelta(days=7),
        choices=[
            {"id": uuid4(), "label": "15 年"},
            {"id": choice, "label": "版本顯示文案改版"},
        ],
    )
    corpus, raw = fixtures()
    control = module.CaseControls.model_validate(raw["cases"]["expert_generic_name"])
    assert module.select_answer(task, question, False, control) == choice
    changed = control.model_copy(update={"version_choice": uuid4()})
    with pytest.raises(ValueError, match="EVAL_ANSWER_NOT_FOUND"):
        module.select_answer(task, question, False, changed)


def test_dry_run_freezes_all_workflow_inputs_without_credentials_or_external_io():
    import os
    import subprocess
    import sys

    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("WHISKY_CLOUDFLARE")
    }
    result = subprocess.run(
        [sys.executable, str(ROOT / "backend/evals/run_t10.py"), "--dry-run"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["case_count"] == 13 and summary["workflow_runs"] == 26
    assert len(summary["corpus_sha256"]) == 64 and len(summary["controls_sha256"]) == 64
    assert summary["model_calls"] == 0
