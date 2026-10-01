"""Public research protocol contracts; no execution is started here."""

from ag_ui.core import Interrupt, RunFinishedEvent, RunFinishedInterruptOutcome

from whisky.modules.research.conclusion_public import (
    concludable_report as concludable_report,
)
from whisky.modules.research.control_public import (
    actor_tasks_closed as actor_tasks_closed,
)
from whisky.modules.research.control_public import cancel_task as cancel_task
from whisky.modules.research.control_public import (
    close_actor_tasks as close_actor_tasks,
)
from whisky.modules.research.control_public import close_plan_tasks as close_plan_tasks
from whisky.modules.research.control_public import (
    controlled_workflow_ids as controlled_workflow_ids,
)
from whisky.modules.research.control_public import (
    plan_tasks_closed as plan_tasks_closed,
)
from whisky.modules.research.control_public import (
    task_control_effect_present as task_control_effect_present,
)
from whisky.modules.research.control_public import task_plan as task_plan
from whisky.modules.research.export_public import (
    AgentTurnExportV1 as AgentTurnExportV1,
)
from whisky.modules.research.export_public import (
    ComparisonExportV1 as ComparisonExportV1,
)
from whisky.modules.research.export_public import (
    ProposalExportV1 as ProposalExportV1,
)
from whisky.modules.research.export_public import (
    QuestionExportV1 as QuestionExportV1,
)
from whisky.modules.research.export_public import (
    ReportCandidateExportV1 as ReportCandidateExportV1,
)
from whisky.modules.research.export_public import (
    ReportCitationExportV1 as ReportCitationExportV1,
)
from whisky.modules.research.export_public import (
    ReportClaimExportV1 as ReportClaimExportV1,
)
from whisky.modules.research.export_public import (
    ReportExportV1 as ReportExportV1,
)
from whisky.modules.research.export_public import (
    ReportPriceExportV1 as ReportPriceExportV1,
)
from whisky.modules.research.export_public import (
    ReportSourceObservationExportV1 as ReportSourceObservationExportV1,
)
from whisky.modules.research.export_public import (
    ResearchInputExportV1 as ResearchInputExportV1,
)
from whisky.modules.research.export_public import (
    SourceObservationExportV1 as SourceObservationExportV1,
)
from whisky.modules.research.export_public import (
    TaskExportV1 as TaskExportV1,
)
from whisky.modules.research.export_public import export_research as export_research
from whisky.modules.research.export_public import (
    research_catalog_export_scopes as research_catalog_export_scopes,
)
from whisky.modules.research.purge_public import (
    purge_actor_research as purge_actor_research,
)
from whisky.modules.research.purge_public import (
    purge_plan_research as purge_plan_research,
)
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
