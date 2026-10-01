import type {components} from "../../../../../contracts/api";
import validFeedback from "../../../../../contracts/bottle-feedback-view.validator.js";
import validFeedbackList from "../../../../../contracts/bottle-feedback-list-view.validator.js";
export type BottleFeedback=components["schemas"]["BottleFeedbackViewV1"];
export type SaveBottleFeedback=components["schemas"]["SaveBottleFeedbackV1"];
export type BottleFeedbackList=components["schemas"]["BottleFeedbackListViewV1"];
export class FeedbackRejected extends Error {
  constructor(public code:string,public status:number) {super(code);}
}
export async function readBottleFeedback(version:string,token:string,signal?:AbortSignal):Promise<BottleFeedback|null> {
  const response=await fetch(`/api/v1/library/feedback/${version}`,{cache:"no-store",headers:{Authorization:`Bearer ${token}`},signal});
  if(response.status===404) {
    const value:unknown=await response.json();
    if(value && typeof value==="object" && "code" in value && value.code==="NOT_FOUND")return null;
    throw new Error("REQUEST_FAILED");
  }
  if(!response.ok)throw new Error(response.status===401 ? "AUTH_REQUIRED" : "REQUEST_FAILED");
  const value:unknown=await response.json();
  if(!validFeedback(value) || value.bottleVersionId!==version || (value.tasting==="not_tasted" && value.tastingReason!==""))throw new Error("INVALID_RESPONSE");
  return value;
}
export async function saveBottleFeedback(command:SaveBottleFeedback,token:string):Promise<BottleFeedback> {
  const response=await fetch("/api/v1/library/feedback",{method:"POST",cache:"no-store",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify(command)});
  if(!response.ok) {
    if([401,404,409,422].includes(response.status)) {
      let code=response.status===401 ? "AUTH_REQUIRED" : "REQUEST_REJECTED";
      try {
        const body:unknown=await response.json();
        const received=body && typeof body==="object" && "code" in body ? body.code : null;
        if(typeof received==="string" && ["AUTH_REQUIRED","NOT_FOUND","REVISION_CONFLICT","IDEMPOTENCY_CONFLICT","IDENTITY_CHANGED","UNKNOWN_BOTTLE_VERSION","INVALID_TASTING_REASON"].includes(received))code=received;
      } catch { /* An HTTP rejection is acknowledged even without a valid body. */ }
      throw new FeedbackRejected(code,response.status);
    }
    throw new Error("REQUEST_FAILED");
  }
  const value:unknown=await response.json();
  if(!validFeedback(value) || value.bottleVersionId!==command.bottleVersionId || value.revision!==command.expectedRevision+1 || value.wantToExplore!==command.wantToExplore || value.tasting!==command.tasting || value.tastingReason!==(command.tastingReason ?? "").trim())throw new Error("INVALID_RESPONSE");
  return value;
}
export async function listBottleFeedback(token:string,cursor:string|null=null,signal?:AbortSignal):Promise<BottleFeedbackList> {
  const query=new URLSearchParams();if(cursor)query.set("cursor",cursor);
  const response=await fetch(`/api/v1/library/feedback${query.size ? `?${query}` : ""}`,{cache:"no-store",headers:{Authorization:`Bearer ${token}`},signal});
  if(!response.ok)throw new Error(response.status===401 ? "AUTH_REQUIRED" : "REQUEST_FAILED");
  const value:unknown=await response.json();
  if(!validFeedbackList(value) || new Set(value.items.map(item=>item.id)).size!==value.items.length || value.items.some(item=>item.tasting==="not_tasted" && item.tastingReason!==""))throw new Error("INVALID_RESPONSE");
  return value;
}
