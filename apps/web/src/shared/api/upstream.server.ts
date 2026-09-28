/** Server-only connection to the dedicated API; never takes an origin from a request. */
export function apiUpstream(origin: string | undefined, fetcher: (request: Request) => Promise<Response> = fetch):
  {fetch(request: Request): Promise<Response>} | undefined {
  if (!origin) return undefined;
  const target=new URL(origin);
  if (!["http:","https:"].includes(target.protocol) || target.pathname!=="/" ||
      target.search || target.hash || target.username || target.password) {
    throw new Error("API configuration requires an HTTP origin without credentials or path");
  }
  return {fetch:request=>{
    const init: RequestInit & {duplex:"half"} = {
      method:request.method, headers:request.headers, body:request.body,
      signal:request.signal, redirect:"manual", cache:"no-store", duplex:"half",
    };
    const url = new URL(request.url);
    return fetcher(new Request(`${target.origin}${url.pathname}${url.search}`, init));
  }};
}
