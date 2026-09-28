export interface PrivateAPI { fetch(request: Request): Promise<Response> }

export function privateFailure(status: number, code: string): Response {
  return Response.json({code, message: "無法完成此請求。", request_id: crypto.randomUUID(), retryable: status >= 500}, {
    status, headers: {"Cache-Control": "no-store"},
  });
}

/** Transport only: the feature adapter must validate its path and method first. */
export async function forwardPrivate(request: Request, upstream?: PrivateAPI): Promise<Response> {
  if (!upstream) return privateFailure(503, "PROXY_UNAVAILABLE");
  const headers = new Headers();
  for (const name of ["authorization", "content-type"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const init: RequestInit & {duplex: "half"} = {
    method: request.method, headers, body: request.body, duplex: "half", redirect: "manual",
    signal: AbortSignal.any([request.signal, AbortSignal.timeout(10_000)]),
  };
  try {
    const result = await upstream.fetch(new Request(
      `http://whisky-api.internal${new URL(request.url).pathname}`, init,
    ));
    if (result.status >= 300 && result.status < 400) {
      await result.body?.cancel();
      return privateFailure(502, "UPSTREAM_REJECTED");
    }
    const safe = new Headers({"Cache-Control": "no-store"});
    for (const name of ["content-type", "www-authenticate"]) {
      const value = result.headers.get(name);
      if (value) safe.set(name, value);
    }
    return new Response(result.body, {status: result.status, headers: safe});
  } catch {
    return privateFailure(503, "PROXY_UNAVAILABLE");
  }
}
