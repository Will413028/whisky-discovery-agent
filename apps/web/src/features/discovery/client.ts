import type { components } from "../../../../../contracts/api";
import validPlan from "../../../../../contracts/plan-view.validator.js";
import validControl from "../../../../../contracts/control-view.validator.js";
import validPlans from "../../../../../contracts/plan-list-view.validator.js";

export type PlanView = components["schemas"]["PlanView"];
export type ControlView = components["schemas"]["ControlView"];
export type PatchRequest = components["schemas"]["PatchConditionsRequest"];

export class RequestRejected extends Error {
  constructor(readonly status:409 | 422) {
    super(status === 409 ? "REVISION_CONFLICT" : "INVALID_CONDITION_PATCH");
  }
}

export async function listPlans(token:string, cursor:string | null, signal?:AbortSignal): Promise<components["schemas"]["PlanListView"]> {
  const query = cursor ? `?${new URLSearchParams({cursor})}` : "";
  const value = await json(await fetch(`/api/v1/plans${query}`, {
    headers:{Authorization:`Bearer ${token}`}, cache:"no-store", signal,
  }));
  if (!validPlans(value)) throw new Error("INVALID_RESPONSE");
  return value;
}

async function json(response: Response): Promise<unknown> {
  if (response.status === 409 || response.status === 422) throw new RequestRejected(response.status);
  if (!response.ok) throw new Error(response.status === 401 ? "AUTH_REQUIRED" : "REQUEST_FAILED");
  return response.json();
}

export async function readPlan(id: string, token: string, signal?: AbortSignal): Promise<PlanView> {
  const value = await json(await fetch(`/api/v1/plans/${id}`, {
    headers:{Authorization:`Bearer ${token}`}, cache:"no-store", signal,
  }));
  if (!validPlan(value) || value.id !== id) throw new Error("INVALID_RESPONSE");
  return value;
}

export async function patchPlan(id: string, token: string, body: PatchRequest): Promise<ControlView> {
  const value = await json(await fetch(`/api/v1/plans/${id}/conditions/patch`, {
    method:"POST", cache:"no-store", headers:{Authorization:`Bearer ${token}`, "Content-Type":"application/json"},
    body:JSON.stringify(body),
  }));
  if (!validControl(value) || value.targetId !== id || value.kind !== "plan.change_conditions") throw new Error("INVALID_RESPONSE");
  return value;
}

export async function readControl(id: string, token: string, signal?: AbortSignal): Promise<ControlView> {
  const value = await json(await fetch(`/api/v1/control-commands/${id}`, {
    headers:{Authorization:`Bearer ${token}`}, cache:"no-store", signal,
  }));
  if (!validControl(value) || value.id !== id) throw new Error("INVALID_RESPONSE");
  return value;
}
