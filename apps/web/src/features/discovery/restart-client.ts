import type {components} from "../../../../../contracts/api";
import validContext from "../../../../../contracts/restart-context-view.validator.js";
import type {ResearchInputV4} from "../research";

export type RestartContext=Omit<components["schemas"]["RestartContextViewV4"],"input"> & {input:ResearchInputV4 & {intent:NonNullable<ResearchInputV4["intent"]>}};

export async function readRestartContext(planId:string,taskId:string,token:string,signal?:AbortSignal):Promise<RestartContext> {
  const response=await fetch(`/api/v1/plans/${planId}/tasks/${taskId}/restart-context`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal});
  if(!response.ok) throw new Error(response.status===401 ? "AUTH_REQUIRED" : "REQUEST_FAILED");
  const value:unknown=await response.json();
  if(!validContext(value) || value.planId!==planId || value.taskId!==taskId || value.input.phase!=="research" || value.input.sourceText!==null || !value.input.intent) throw new Error("INVALID_RESPONSE");
  const intent=value.input.intent;
  return {...value,input:{schemaVersion:4,phase:"research",sourceText:null,intent:{...intent,origin_query:intent.origin_query ?? null,explore_feature:intent.explore_feature ?? null,contrast:intent.contrast ?? null}}};
}
