import {forwardPrivate, privateFailure, type PrivateAPI} from "../../shared/api/private-forward";

export async function planProxy(request: Request, upstream?: PrivateAPI): Promise<Response> {
  const url = new URL(request.url);
  const collection = url.pathname === "/api/v1/plans";
  const resource = /^\/api\/v1\/plans\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(url.pathname);
  const history = /^\/api\/v1\/plans\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/tasks$/.test(url.pathname);
  if (!collection && !resource && !history) return privateFailure(404, "NOT_FOUND");
  if (url.search && (!(collection || history) || request.method !== "GET")) return privateFailure(404, "NOT_FOUND");
  if (request.method !== "GET" && !(collection && request.method === "POST")) return privateFailure(405, "METHOD_NOT_ALLOWED");
  for (const name of url.searchParams.keys()) {
    if (name !== "limit" && name !== "cursor") return privateFailure(404, "NOT_FOUND");
    if (url.searchParams.getAll(name).length !== 1) return privateFailure(422, "INVALID_REQUEST");
  }
  const limit = url.searchParams.get("limit");
  const cursor = url.searchParams.get("cursor");
  if ((limit !== null && (!/^\d+$/.test(limit) || Number(limit) < 1 || Number(limit) > 50)) ||
      (cursor !== null && (cursor.length > 512 || !/^[A-Za-z0-9_-]+={0,2}$/.test(cursor)))) {
    return privateFailure(422, "INVALID_REQUEST");
  }
  return forwardPrivate(request, upstream);
}
