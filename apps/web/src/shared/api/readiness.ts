/** Public availability only; no request credentials or upstream details. */
export async function readinessProbe(upstream?: {fetch(request: Request): Promise<Response>}): Promise<Response> {
  let ready = false;
  if (upstream) {
    try {
      const result = await upstream.fetch(new Request("http://whisky-api.internal/health/ready", {
        method: "GET", redirect: "manual", cache: "no-store",
        signal: AbortSignal.timeout(2_000),
      }));
      ready = result.status === 200;
      await result.body?.cancel();
    } catch {
      ready = false;
    }
  }
  return Response.json({status: ready ? "ok" : "unavailable"}, {
    status: ready ? 200 : 503,
    headers: {"Cache-Control": "no-store"},
  });
}
