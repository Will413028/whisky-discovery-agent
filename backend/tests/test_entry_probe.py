import runpy
from pathlib import Path
from uuid import uuid4

from whisky.modules.research.observation import ObserveInput

fixture = runpy.run_path(str(Path(__file__).parents[2] / "deploy/entry_probe.py"))


async def test_synthetic_probe_keeps_latest_view_on_reconnect_and_checks_all_keys():
    now = [0.0]
    owner = uuid4()
    source = fixture["SyntheticSource"](owner, lambda: now[0])
    request = ObserveInput(
        task_id=fixture["TASK"], run_id=fixture["RUN"], conditions_revision=1
    )
    for changes in (
        {"task_id": uuid4()},
        {"run_id": uuid4()},
        {"conditions_revision": 2},
    ):
        assert await source.read(request.model_copy(update=changes), owner) is None
    assert await source.read(request, uuid4()) is None
    assert source.started is None
    first = await source.read(request, owner)
    assert first is not None, "authorized synthetic observation must expose version 1"
    assert first.view_version == 1
    assert "合成" in first.stage
    now[0] = 1.9
    assert (await source.read(request, owner)).view_version == 1
    now[0] = 2
    second = await source.read(request, owner)
    assert second.view_version == 2
    assert second.status == "researching"
    now[0] = 65
    resumed = await source.read(request, owner)
    assert resumed.view_version == 2
    assert resumed.status == "researching"
