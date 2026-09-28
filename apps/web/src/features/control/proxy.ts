import {forwardPrivate, privateFailure, type PrivateAPI} from "../../shared/api/private-forward";

const uuid = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const taskCancel = new RegExp(`^/api/v1/tasks/${uuid}/cancel$`);
const planConditions = new RegExp(`^/api/v1/plans/${uuid}/conditions$`);
const planDelete = new RegExp(`^/api/v1/plans/${uuid}/delete$`);
const commandRead = new RegExp(`^/api/v1/control-commands/${uuid}$`);

export function isControlPath(pathname: string): boolean {
  return taskCancel.test(pathname) || planConditions.test(pathname) ||
    planDelete.test(pathname) || pathname === "/api/v1/me/delete" || commandRead.test(pathname);
}

export async function controlProxy(request: Request, upstream?: PrivateAPI): Promise<Response> {
  const url = new URL(request.url);
  if (!isControlPath(url.pathname) || url.search) return privateFailure(404, "NOT_FOUND");
  const method = commandRead.test(url.pathname) ? "GET" : "POST";
  if (request.method !== method) return privateFailure(405, "METHOD_NOT_ALLOWED");
  return forwardPrivate(request, upstream);
}
