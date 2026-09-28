from whisky.modules.research.public import waiting_event


def test_waiting_turn_finishes_as_interrupt_not_success():
    event = waiting_event("fixture-task", "fixture-run", "fixture-question")
    wire = event.model_dump(by_alias=True, exclude_none=True)
    assert wire.get("outcome") == {
        "type": "interrupt",
        "interrupts": [{"id": "fixture-question", "reason": "input_required"}],
    }
