import type { components } from "../../../../../contracts/api";
import validTask from "../../../../../contracts/task-view.validator.js";
import { readEvents } from "./transport";
import type { TaskView } from "./state";

export type ReportView = components["schemas"]["ReportView"];
export type ResearchCommandView = components["schemas"]["ResearchCommandView"];
export type ResearchInputV4 = components["schemas"]["ResearchInputV4Input"];

export async function startResearchV4(token:string,plan:{id:string;conditionsRevision:number},key:string,threadId:string,runId:string,input:ResearchInputV4):Promise<TaskView> {
  return startResearchCommand(token,plan,threadId,runId,{
    type:"start_v4",key,planId:plan.id,conditionsRevision:plan.conditionsRevision,input,
  });
}

async function jsonResponse(response: Response): Promise<unknown> {
  if (!response.ok) throw new Error(response.status === 401 ? "AUTH_REQUIRED" : "REQUEST_FAILED");
  return response.json();
}

export async function createPlan(token: string, key: string, goal: string, budgetTwd: string | null, preferences:components["schemas"]["Preference"][]=[]): Promise<{id:string; conditionsRevision:number}> {
  const body:components["schemas"]["CreatePlanInput"]={key,conditions:{schema_version:1,entry:"beginner",goal,budget_twd:budgetTwd,starting_bottle:null,preferences}};
  const value = await jsonResponse(await fetch("/api/v1/plans", {
    method:"POST", cache:"no-store", headers:{Authorization:`Bearer ${token}`, "Content-Type":"application/json"},
    body:JSON.stringify(body),
  }));
  if (!value || typeof value !== "object" || !("id" in value) || typeof value.id !== "string" ||
      !("conditionsRevision" in value) || typeof value.conditionsRevision !== "number") throw new Error("INVALID_RESPONSE");
  return {id:value.id, conditionsRevision:value.conditionsRevision};
}

export async function startResearch(token: string, plan: {id:string; conditionsRevision:number}, key: string, threadId: string, runId: string): Promise<TaskView> {
  return startResearchCommand(token,plan,threadId,runId,{
    type:"start",key,planId:plan.id,conditionsRevision:plan.conditionsRevision,
  });
}

type StartCommandV4 = components["schemas"]["StartCommandV4"];
type StartCommandV1 = Omit<StartCommandV4,"input" | "type"> & {type:"start"};

async function startResearchCommand(token:string,plan:{id:string;conditionsRevision:number},threadId:string,runId:string,command:StartCommandV1 | StartCommandV4):Promise<TaskView> {
  const controller = new AbortController();
  let task: TaskView | null = null;
  try {
    await readEvents(signal => fetch("/agent", {
      method:"POST", cache:"no-store", headers:{Authorization:`Bearer ${token}`, "Content-Type":"application/json"}, signal,
      body:JSON.stringify({threadId, runId, messages:[], state:{}, tools:[], context:[],
        forwardedProps:command}),
    }), event => {
      if (event.type === "STATE_SNAPSHOT" && validTask(event.snapshot) &&
          event.snapshot.threadId === threadId && event.snapshot.conditionsRevision === plan.conditionsRevision) {
        task = event.snapshot;
        controller.abort();
      }
    }, controller.signal);
  } catch (error) {
    if (!task) throw error;
  }
  if (!task) throw new Error("INVALID_RESPONSE");
  return task;
}

export async function readTask(taskId: string, token: string, signal?: AbortSignal): Promise<TaskView> {
  const value = await jsonResponse(await fetch(`/api/v1/tasks/${taskId}`, {
    headers:{Authorization:`Bearer ${token}`}, cache:"no-store", signal,
  }));
  if (!validTask(value) || value.taskId !== taskId) throw new Error("INVALID_RESPONSE");
  return value;
}

export async function listOpenTasks(token: string, signal?: AbortSignal): Promise<TaskView[]> {
  const value = await jsonResponse(await fetch("/api/v1/tasks", {
    headers:{Authorization:`Bearer ${token}`}, cache:"no-store", signal,
  }));
  if (!Array.isArray(value) || !value.every(validTask)) throw new Error("INVALID_RESPONSE");
  return value;
}

export async function answerQuestion(task: TaskView, answer: string, key: string, token: string): Promise<ResearchCommandView> {
  if (!task.question) throw new Error("QUESTION_CLOSED");
  const value = await jsonResponse(await fetch(`/api/v1/tasks/${task.taskId}/clarifications/${task.question.id}/answer`, {
    method:"POST", cache:"no-store", headers:{Authorization:`Bearer ${token}`, "Content-Type":"application/json"},
    body:JSON.stringify({key, conditionsRevision:task.conditionsRevision, waitingVersion:task.question.waitingVersion, answer}),
  }));
  if (!value || typeof value !== "object" || !("id" in value) || typeof value.id !== "string" ||
      !("taskId" in value) || value.taskId !== task.taskId || !("acceptance" in value) ||
      !["accepted", "acceptance_pending"].includes(String(value.acceptance))) throw new Error("INVALID_RESPONSE");
  return value as ResearchCommandView;
}

export async function readReport(task: TaskView, token: string, signal?: AbortSignal): Promise<ReportView> {
  if (!task.reportId) throw new Error("REPORT_UNAVAILABLE");
  const value = await jsonResponse(await fetch(`/api/v1/reports/${task.reportId}`, {
    headers:{Authorization:`Bearer ${token}`}, cache:"no-store", signal,
  }));
  if (!value || typeof value !== "object" || !("id" in value) || value.id !== task.reportId ||
      !("taskId" in value) || value.taskId !== task.taskId || !("summary" in value) ||
      typeof value.summary !== "string") throw new Error("INVALID_RESPONSE");
  return value as ReportView;
}
