import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from whisky.modules.research.source_reader import SourcePage, SourceReadError

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location(
    "whisky_t10_source", ROOT / "backend/evals/t10_source.py"
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


async def test_injected_failure_is_single_scoped_and_traceable_before_real_delegate(
    monkeypatch,
):
    monkeypatch.setattr(
        module.activity, "info", lambda: SimpleNamespace(workflow_id="designated")
    )

    class Delegate:
        calls = []

        async def read(self, url):
            self.calls.append(url)
            return SourcePage(
                "https://www.theglenlivet.com/final", "public fixture text"
            )

    delegate = Delegate()
    reader = module.EvalSourceReader(inject_first=True, delegate=delegate)
    reader.fail_first_workflows.add("designated")
    with pytest.raises(SourceReadError, match="SOURCE_HTTP_ERROR"):
        await reader.read("https://www.theglenlivet.com/unavailable")
    assert delegate.calls == []
    page = await reader.read("https://www.theglenlivet.com/alternative")
    assert page.final_url == "https://www.theglenlivet.com/final"
    assert delegate.calls == ["https://www.theglenlivet.com/alternative"]
    assert reader.calls["designated"][0]["fault_injection"] is True
    assert reader.calls["designated"][1]["status"] == "ok"
    monkeypatch.setattr(
        module.activity, "info", lambda: SimpleNamespace(workflow_id="unrelated")
    )
    await reader.read("https://www.theglenlivet.com/unrelated")
    assert len(delegate.calls) == 2


async def test_fault_injection_never_bypasses_the_existing_source_url_guard(
    monkeypatch,
):
    monkeypatch.setattr(
        module.activity, "info", lambda: SimpleNamespace(workflow_id="designated")
    )
    reader = module.EvalSourceReader(inject_first=True)
    reader.fail_first_workflows.add("designated")
    with pytest.raises(SourceReadError, match="SOURCE_URL_REJECTED"):
        await reader.read("https://example.invalid/unsupported")
    assert not any(
        row.get("fault_injection") for row in reader.calls.get("designated", [])
    )
