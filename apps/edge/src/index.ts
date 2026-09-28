export type WebBinding = {fetch(request: Request): Promise<Response>};

export default {
  async fetch(request: Request, env: {WHISKY_WEB?: WebBinding}): Promise<Response> {
    if (!env.WHISKY_WEB) return unavailable();
    const publicURL=new URL(request.url);
    const headers=new Headers(request.headers);
    headers.set("x-forwarded-host",publicURL.host);
    headers.set("x-forwarded-proto",publicURL.protocol.slice(0,-1));
    headers.delete("forwarded");
    headers.delete("x-forwarded-for");
    for (const name of ["connection","upgrade","transfer-encoding"]) headers.delete(name);
    const init: RequestInit & {duplex:"half"} = {
      method:request.method,headers,body:request.body,redirect:"manual",duplex:"half",
      signal:AbortSignal.any([request.signal,AbortSignal.timeout(75_000)]),
    };
    try {
      const response=await env.WHISKY_WEB.fetch(new Request(
        `http://whisky-web.internal${publicURL.pathname}${publicURL.search}`,init,
      ));
      return new Response(response.body,{status:response.status,statusText:response.statusText,headers:response.headers});
    } catch { return unavailable(); }
  },
};

function unavailable(): Response {
  return Response.json({code:"WEB_UNAVAILABLE",message:"暫時無法連線，請稍後重試。"},
    {status:503,headers:{"Cache-Control":"no-store"}});
}
