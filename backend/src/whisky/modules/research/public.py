"""Public research protocol contracts; no execution is started here."""

from ag_ui.core import Interrupt, RunFinishedEvent, RunFinishedInterruptOutcome

from whisky.modules.research.control_public import cancel_task as cancel_task
from whisky.modules.research.control_public import (
    close_actor_tasks as close_actor_tasks,
)
from whisky.modules.research.control_public import close_plan_tasks as close_plan_tasks
from whisky.modules.research.control_public import (
    controlled_workflow_ids as controlled_workflow_ids,
)
from whisky.modules.research.control_public import task_plan as task_plan
from whisky.modules.research.views import QuestionChoiceView
from whisky.modules.research.views import TaskView as TaskView


def waiting_event(
    thread_id: str,
    run_id: str,
    question_id: str,
    *,
    prompt: str | None = None,
    choices: tuple[QuestionChoiceView, ...] = (),
    expires_at: str | None = None,
) -> RunFinishedEvent:
    schema = (
        {
            "type": "object",
            "properties": {
                "answer": {
                    "type": "string",
                    "enum": [str(choice.id) for choice in choices],
                }
            },
            "required": ["answer"],
            "additionalProperties": False,
        }
        if choices
        else None
    )
    return RunFinishedEvent(
        thread_id=thread_id,
        run_id=run_id,
        outcome=RunFinishedInterruptOutcome(
            interrupts=[
                Interrupt(
                    id=question_id,
                    reason="input_required",
                    message=prompt,
                    response_schema=schema,
                    expires_at=expires_at,
                )
            ]
        ),
    )
