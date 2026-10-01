import type {TaskView} from "./state";
import type {components} from "../../../../../contracts/api";
import validProposal from "../../../../../contracts/preference-proposal-view.validator.js";

export type PreferenceProposalView = components["schemas"]["PreferenceProposalViewV4"];

export async function readPreferenceProposal(task:TaskView,token:string,signal?:AbortSignal):Promise<PreferenceProposalView | null> {
  if(task.status!=="needs_input" || !task.question) return null;
  const response=await fetch(`/api/v1/tasks/${task.taskId}/preference-proposal`,{
    headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal,
  });
  if(response.status===404) return null;
  if(!response.ok) throw new Error(response.status===401 ? "AUTH_REQUIRED" : "REQUEST_FAILED");
  const value:unknown=await response.json();
  if(!validProposal(value) || value.taskId!==task.taskId || value.questionId!==task.question.id ||
    value.conditionsRevision!==task.conditionsRevision || value.waitingVersion!==task.question.waitingVersion) throw new Error("INVALID_RESPONSE");
  return value;
}
