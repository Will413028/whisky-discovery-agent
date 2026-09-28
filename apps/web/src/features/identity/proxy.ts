import {forwardPrivate, privateFailure as failure, type PrivateAPI} from "../../shared/api/private-forward";

export async function proxy(request: Request, upstream?: PrivateAPI): Promise<Response> {
  const url = new URL(request.url);
  const allowed = url.pathname === "/api/v1/me" || /^\/api\/v1\/actors\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(url.pathname);
  if (!allowed || url.search) return failure(404, "NOT_FOUND");
  if (request.method !== "GET") return failure(405, "METHOD_NOT_ALLOWED");
  return forwardPrivate(request, upstream);
}
