import {afterEach,expect,test,vi} from "vitest";
import {GET,POST} from "../../app/api/[...path]/route";
const id="00000000-0000-4000-8000-000000000001";
afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();});
test.each(["save","list","read","context","revisit"])("library %s uses the fixed private upstream",async mode=>{
  vi.stubEnv("WHISKY_API_ORIGIN","http://127.0.0.1:9000");
  const upstream=vi.fn(async(_request:Request)=>Response.json({schemaVersion:1}));vi.stubGlobal("fetch",upstream);
  const path=mode==="context" ? `/api/v1/library/reports/${id}/conclusion-context` : mode==="revisit" ? `/api/v1/library/conclusions/${id}/revisit` : mode==="read" ? `/api/v1/library/conclusions/${id}` : `/api/v1/library/conclusions${mode==="list" ? `?planId=${id}&limit=2` : ""}`;
  const request=new Request(`https://web.example${path}`,{method:mode==="save" ? "POST" : "GET",headers:{Authorization:"Bearer fixture",Cookie:"ignored=value"},...(mode==="save" ? {body:"{}"}: {})});
  const result=await (mode==="save" ? POST(request):GET(request));
  expect(result.status).toBe(200);expect(result.headers.get("Cache-Control")).toBe("no-store");
  const forwarded=upstream.mock.calls[0]?.[0] as Request|undefined;
  expect(forwarded?.url).toBe(`http://127.0.0.1:9000${path}`);
  expect(forwarded?.headers.get("Authorization")).toBe("Bearer fixture");
  expect(forwarded?.headers.get("Cookie")).toBeNull();
});
