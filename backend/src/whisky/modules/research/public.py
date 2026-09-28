"""Public research protocol contracts; no execution is started here."""

from ag_ui.core import Interrupt, RunFinishedEvent, RunFinishedInterruptOutcome

from whisky.modules.research.views import TaskView as TaskView


def waiting_event(thread_id: str, run_id: str, question_id: str) -> RunFinishedEvent:
    return RunFinishedEvent(
        thread_id=thread_id,
        run_id=run_id,
        outcome=RunFinishedInterruptOutcome(
            interrupts=[Interrupt(id=question_id, reason="input_required")]
        ),
    )
