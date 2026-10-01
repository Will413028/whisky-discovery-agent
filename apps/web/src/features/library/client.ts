import type {components} from "../../../../../contracts/api";
import validConclusion from "../../../../../contracts/conclusion-view.validator.js";
import validConclusions from "../../../../../contracts/conclusion-list-view.validator.js";
import validContext from "../../../../../contracts/conclusion-context-view.validator.js";
import validRevisit from "../../../../../contracts/conclusion-revisit-view.validator.js";

export type Conclusion=components["schemas"]["ConclusionViewV1"];
export type SaveConclusion=components["schemas"]["SaveConclusionV1"];
export type ConclusionRevisit=components["schemas"]["ConclusionRevisitViewV1"];
export async function revisitConclusion(saved:Conclusion,token:string,signal?:AbortSignal):Promise<ConclusionRevisit> {
  const response=await fetch(`/api/v1/library/conclusions/${saved.id}/revisit`,{cache:"no-store",headers:{Authorization:`Bearer ${token}`},signal});
  if(!response.ok) throw new Error(response.status===401 ? "AUTH_REQUIRED" : "REQUEST_FAILED");
  const value:unknown=await response.json();
  const versions=[...(saved.selectedVersionId ? [saved.selectedVersionId] : []),...saved.alternativeVersionIds];
  if(!validRevisit(value) || value.conclusionId!==saved.id || value.planId!==saved.planId || value.conditionsRevision!==saved.conditionsRevision || value.budgetTwd!==(saved.conditions.budget_twd ?? null) || value.items.length!==versions.length || new Set(value.items.map(item=>item.bottleVersionId)).size!==versions.length || value.items.some(item=>!versions.includes(item.bottleVersionId))) throw new Error("INVALID_RESPONSE");
  return value;
}
export class ConclusionRejected extends Error {
  constructor(public code:string,public status:number) {super(code);}
}
export async function readConclusionContext(reportId:string,taskId:string,revision:number,token:string,signal?:AbortSignal):Promise<components["schemas"]["ConclusionContextViewV1"]> {
  const response=await fetch(`/api/v1/library/reports/${reportId}/conclusion-context`,{cache:"no-store",headers:{Authorization:`Bearer ${token}`},signal});
  if(!response.ok) throw new Error(response.status===401 ? "AUTH_REQUIRED" : "REQUEST_FAILED");
  const value:unknown=await response.json();
  if(!validContext(value) || value.reportId!==reportId || value.taskId!==taskId || value.conditionsRevision!==revision) throw new Error("INVALID_RESPONSE");
  return value;
}
export async function listConclusions(planId:string,token:string,cursor:string|null=null,signal?:AbortSignal):Promise<components["schemas"]["ConclusionListViewV1"]> {
  const query=new URLSearchParams({planId});if(cursor) query.set("cursor",cursor);
  const response=await fetch(`/api/v1/library/conclusions?${query}`,{cache:"no-store",headers:{Authorization:`Bearer ${token}`},signal});
  if(!response.ok) throw new Error(response.status===401 ? "AUTH_REQUIRED" : "REQUEST_FAILED");
  const value:unknown=await response.json();
  if(!validConclusions(value) || value.planId!==planId || value.items.some(item=>item.planId!==planId || (item.selectedVersionId!==null && item.alternativeVersionIds.includes(item.selectedVersionId)))) throw new Error("INVALID_RESPONSE");
  return value;
}
export async function saveConclusion(command:SaveConclusion,token:string):Promise<Conclusion> {
  const response=await fetch("/api/v1/library/conclusions",{
    method:"POST",cache:"no-store",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify(command),
  });
  if(!response.ok) {
    if([401,403,404,409,422].includes(response.status)) {
      let code=response.status===401 ? "AUTH_REQUIRED" : "REQUEST_REJECTED";
      try {
        const body:unknown=await response.json();
        const received=body && typeof body==="object" && "code" in body ? body.code : null;
        if(typeof received==="string" && ["AUTH_REQUIRED","ACTOR_DISABLED","NOT_FOUND","REVISION_CONFLICT","IDEMPOTENCY_CONFLICT","IDENTITY_CHANGED","INVALID_REPORT_CANDIDATES","NOT_A_REPORT_CANDIDATE","INVALID_REASON","INVALID_TRADEOFF"].includes(received)) code=received;
      } catch {/* The HTTP status still acknowledges a rejected write. */}
      throw new ConclusionRejected(code,response.status);
    }
    throw new Error("REQUEST_FAILED");
  }
  const value:unknown=await response.json();
  if(!validConclusion(value) || value.planId!==command.planId || value.reportId!==command.reportId
    || value.conditionsRevision!==command.expectedConditionsRevision || value.selectedVersionId!==(command.selectedVersionId ?? null)
    || (value.selectedVersionId!==null && value.alternativeVersionIds.includes(value.selectedVersionId))) throw new Error("INVALID_RESPONSE");
  return value;
}
