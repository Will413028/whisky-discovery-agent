export interface PrivateAPI { fetch(request: Request): Promise<Response> }

export async function proxy(request: Request, upstream?: PrivateAPI): Promise<Response> {
  const url = new URL(request.url);
  const allowed = url.pathname === "/api/v1/me" || /^\/api\/v1\/actors\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(url.pathname);
  if (!allowed || url.search) return failure(404, "NOT_FOUND");
  if (request.method !== "GET") return failure(405, "METHOD_NOT_ALLOWED");
  if (!upstream) return failure(503, "PROXY_UNAVAILABLE");
  const headers = new Headers();
  const authorization = request.headers.get("authorization");
  if (authorization) headers.set("authorization", authorization);
  try {
    const result = await upstream.fetch(new Request(`http://whisky-api.internal${url.pathname}`, {
      method: "GET", headers, redirect: "manual",
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(10_000)]),
    }));
    if (result.status >= 300 && result.status < 400) return failure(502, "UPSTREAM_REJECTED");
    const safe = new Headers({ "Cache-Control": "no-store" });
    for (const name of ["content-type", "www-authenticate"]) {
      const value = result.headers.get(name);
      if (value) safe.set(name, value);
    }
    return new Response(result.body, { status: result.status, headers: safe });
  } catch {
    return failure(503, "PROXY_UNAVAILABLE");
  }
}

function failure(status: number, code: string): Response {
  return Response.json({ code, message: "無法完成此請求。", request_id: crypto.randomUUID(), retryable: status >= 500 }, {
    status, headers: { "Cache-Control": "no-store" },
  });
}
