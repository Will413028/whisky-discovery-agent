import type { components } from "../../../../../contracts/api";
import valid from "../../../../../contracts/task-view.validator.js";

export type TaskView = components["schemas"]["TaskView"];
export type ResearchState = {
  taskId: string;
  threadId: string;
  conditionsRevision: number;
  connection: number;
  view: TaskView | null;
  connected: boolean;
};

export function snapshot(state: ResearchState, value: unknown, connection: number): ResearchState {
  if (connection !== state.connection || !valid(value) ||
    value.taskId !== state.taskId || value.threadId !== state.threadId ||
    value.conditionsRevision !== state.conditionsRevision ||
    (state.view !== null && value.viewVersion <= state.view.viewVersion)) return state;
  return {...state, view:value};
}

export function disconnected(state: ResearchState, connection: number): ResearchState {
  return connection === state.connection ? {...state, connected:false} : state;
}
