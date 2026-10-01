import type {components} from "../../../../../contracts/api";
import validPreferences from "../../../../../contracts/long-term-preferences-view.validator.js";
export type LongTermPreferences=components["schemas"]["LongTermPreferencesViewV1"];
export type SaveLongTermPreferences=components["schemas"]["SaveLongTermPreferencesV1"];
export type LongTermPreference=components["schemas"]["LongTermPreferenceV1"];
export class PreferencesRejected extends Error {constructor(public code:string,public status:number){super(code);}}
function validate(value:unknown):LongTermPreferences {
  if(!validPreferences(value) || new Set(value.preferences.map(item=>item.description)).size!==value.preferences.length || value.preferences.some(item=>(item.sourceFeedbackId==null)!==(item.sourceFeedbackRevision==null)) || (value.revision===0 && (value.preferences.length!==0 || value.updatedAt!==null)) || (value.revision>0 && value.updatedAt===null))throw new Error("INVALID_RESPONSE");
  return value;
}
export function canonicalPreference(value:LongTermPreference):LongTermPreference {
  return {description:value.description.trim(),intent:value.intent,strength:value.strength,certainty:"user_stated",statement:value.statement.trim(),sourceFeedbackId:value.sourceFeedbackId ?? null,sourceFeedbackRevision:value.sourceFeedbackRevision ?? null};
}
export async function readLongTermPreferences(token:string,signal?:AbortSignal):Promise<LongTermPreferences>{
  const response=await fetch("/api/v1/library/preferences",{cache:"no-store",headers:{Authorization:`Bearer ${token}`},signal});
  if(!response.ok)throw new Error(response.status===401 ? "AUTH_REQUIRED" : "REQUEST_FAILED");
  return validate(await response.json());
}
export async function saveLongTermPreferences(command:SaveLongTermPreferences,token:string):Promise<LongTermPreferences>{
  const response=await fetch("/api/v1/library/preferences",{method:"POST",cache:"no-store",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify(command)});
  if(!response.ok){
    if([401,403,404,409,422].includes(response.status)){
      let code=response.status===401 ? "AUTH_REQUIRED" : "REQUEST_REJECTED";
      try {
        const body:unknown=await response.json();const received=body && typeof body==="object" && "code" in body ? body.code : null;
        if(typeof received==="string" && ["AUTH_REQUIRED","ACTOR_DISABLED","NOT_FOUND","REVISION_CONFLICT","IDEMPOTENCY_CONFLICT","IDENTITY_CHANGED","SOURCE_FEEDBACK_CHANGED"].includes(received))code=received;
      } catch { /* Acknowledged rejection remains distinct from an unknown result. */ }
      throw new PreferencesRejected(code,response.status);
    }
    throw new Error("REQUEST_FAILED");
  }
  const value=validate(await response.json());
  if(value.revision!==command.expectedRevision+1 || JSON.stringify(value.preferences.map(canonicalPreference))!==JSON.stringify(command.preferences.map(canonicalPreference)))throw new Error("INVALID_RESPONSE");
  return value;
}
