import {forwardPrivate, privateFailure, type PrivateAPI} from "../../shared/api/private-forward";

/** Anonymous catalog reads use the fixed API connection and carry no credentials. */
export function catalogProxy(request: Request, upstream?: PrivateAPI): Promise<Response> {
  const url = new URL(request.url);
  if (url.pathname !== "/api/v1/catalog" || url.search) return Promise.resolve(privateFailure(404, "NOT_FOUND"));
  if (request.method !== "GET") return Promise.resolve(privateFailure(405, "METHOD_NOT_ALLOWED"));
  return forwardPrivate(new Request(request.url, {method:"GET", signal:request.signal}), upstream);
}
