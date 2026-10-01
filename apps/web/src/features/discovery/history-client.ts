import type {components} from "../../../../../contracts/api";
import validHistory from "../../../../../contracts/task-history-view.validator.js";

export type HistoryItem=components["schemas"]["TaskHistoryItem"];

export async function listHistory(id:string, token:string, cursor:string | null, signal?:AbortSignal):Promise<components["schemas"]["TaskHistoryView"]> {
  const query=cursor ? `?${new URLSearchParams({cursor})}` : "";
  const response=await fetch(`/api/v1/plans/${id}/tasks${query}`,{
    headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal,
  });
  if (!response.ok) throw new Error(response.status===401 ? "AUTH_REQUIRED" : "REQUEST_FAILED");
  const value:unknown=await response.json();
  if (!validHistory(value)) throw new Error("INVALID_RESPONSE");
  return value;
}
