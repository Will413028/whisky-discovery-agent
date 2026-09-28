import {forwardPrivate, privateFailure, type PrivateAPI} from "../../shared/api/private-forward";

export interface ObservationUpstream { fetch(request: Request): Promise<Response> }

export async function researchReadProxy(request: Request, upstream?: PrivateAPI): Promise<Response> {
  const url = new URL(request.url);
  const uuid = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
  const read = url.pathname === "/api/v1/tasks" || new RegExp(`^/api/v1/(tasks|commands|reports)/${uuid}$`).test(url.pathname);
  const answer = new RegExp(`^/api/v1/tasks/${uuid}/clarifications/${uuid}/answer$`).test(url.pathname);
  if ((!read && !answer) || url.search) {
    return privateFailure(404, "NOT_FOUND");
  }
  if (request.method !== (answer ? "POST" : "GET")) return privateFailure(405, "METHOD_NOT_ALLOWED");
  return forwardPrivate(request, upstream);
}

// Stream transport; application authentication and commands remain at the API boundary.
export async function researchStreamProxy(request: Request, upstream?: ObservationUpstream): Promise<Response> {
  const url = new URL(request.url);
  if (!["/agent", "/agent/observe"].includes(url.pathname) || url.search) return failure(404, "NOT_FOUND");
  if (request.method !== "POST") return failure(405, "METHOD_NOT_ALLOWED");
  if (!upstream) return failure(503, "PROXY_UNAVAILABLE");
  const headers = new Headers({"Content-Type":"application/json"});
  const authorization = request.headers.get("authorization");
  if (authorization) headers.set("authorization", authorization);
  const chunks: Uint8Array[] = [];
  let size = 0;
  const reader = request.body?.getReader();
  try {
    if (reader) {
      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > 16_384) {
          await reader.cancel();
          return failure(413, "REQUEST_TOO_LARGE");
        }
        chunks.push(value);
      }
    }
    const body = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {body.set(chunk, offset); offset += chunk.length;}
    const response = await upstream.fetch(new Request(`http://whisky-api.internal${url.pathname}`, {
      method:"POST", body: size ? body : undefined, headers, redirect:"manual",
      signal:AbortSignal.any([request.signal, AbortSignal.timeout(70_000)]),
    }));
    if ((response.status >= 300 && response.status < 400) ||
      (response.ok && !response.headers.get("content-type")?.startsWith("text/event-stream"))) {
      await response.body?.cancel();
      return failure(502, "UPSTREAM_REJECTED");
    }
    const safe = new Headers({"Cache-Control":"no-store"});
    for (const name of ["content-type", "www-authenticate", "x-command-id"]) {
      const value = response.headers.get(name);
      if (value) safe.set(name, value);
    }
    return new Response(response.body, {status:response.status, headers:safe});
  } catch {
    return failure(503, "PROXY_UNAVAILABLE");
  } finally { reader?.releaseLock(); }
}

function failure(status:number, code:string): Response {
  return Response.json({code, message:"無法完成此請求。", request_id:crypto.randomUUID(), retryable:status >= 500}, {status, headers:{"Cache-Control":"no-store"}});
}
