import {forwardPrivate, privateFailure, type PrivateAPI} from "../../shared/api/private-forward";

export async function planProxy(request: Request, upstream?: PrivateAPI): Promise<Response> {
  const url = new URL(request.url);
  const collection = url.pathname === "/api/v1/plans";
  const resource = /^\/api\/v1\/plans\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(url.pathname);
  if ((!collection && !resource) || url.search) return privateFailure(404, "NOT_FOUND");
  if (request.method !== (collection ? "POST" : "GET")) return privateFailure(405, "METHOD_NOT_ALLOWED");
  return forwardPrivate(request, upstream);
}
