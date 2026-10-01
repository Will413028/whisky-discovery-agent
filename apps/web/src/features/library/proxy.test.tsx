import {afterEach,expect,test,vi} from "vitest";
import {GET,POST} from "../../app/api/[...path]/route";
const id="00000000-0000-4000-8000-000000000001";
afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();});
test.each(["GET","POST"])("account preferences %s uses fixed private transport",async method=>{
  vi.stubEnv("WHISKY_API_ORIGIN","http://127.0.0.1:9000");
  const upstream=vi.fn(async(_request:Request)=>Response.json({schemaVersion:1}));vi.stubGlobal("fetch",upstream);
  const request=new Request("https://web.example/api/v1/library/preferences",{method,headers:{Authorization:"Bearer fixture"},...(method==="POST" ? {body:"{}"}: {})});
  const result=await(method==="POST" ? POST(request):GET(request));
  expect(result.status).toBe(200);
  expect((upstream.mock.calls[0]?.[0] as Request|undefined)?.url).toBe("http://127.0.0.1:9000/api/v1/library/preferences");
});
test.each(["save","read","list"])("feedback %s keeps fixed private transport",async mode=>{
  vi.stubEnv("WHISKY_API_ORIGIN","http://127.0.0.1:9000");
  const upstream=vi.fn(async(_request:Request)=>Response.json({schemaVersion:1}));vi.stubGlobal("fetch",upstream);
  const path=mode==="read" ? `/api/v1/library/feedback/${id}` : `/api/v1/library/feedback${mode==="list" ? "?limit=2" : ""}`;
  const request=new Request(`https://web.example${path}`,{method:mode==="save" ? "POST" : "GET",headers:{Authorization:"Bearer fixture"},...(mode==="save" ? {body:"{}"}: {})});
  const result=await(mode==="save" ? POST(request):GET(request));
  expect(result.status).toBe(200);
  expect(result.headers.get("Cache-Control")).toBe("no-store");
  expect((upstream.mock.calls[0]?.[0] as Request|undefined)?.url).toBe(`http://127.0.0.1:9000${path}`);
});
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
test("export allows only the fixed private GET download",async()=>{
  vi.stubEnv("WHISKY_API_ORIGIN","http://127.0.0.1:9000");
  const fetch=vi.fn(async()=>Response.json({fixture:"export"},{headers:{"x-export-owner":id,"x-export-schema":"1","x-export-generation":"1","x-export-bytes":"20","set-cookie":"untrusted=value","content-disposition":"attachment; filename=untrusted.txt"}}));vi.stubGlobal("fetch",fetch);
  const response=await GET(new Request("https://fixture.example/api/v1/library/export",{headers:{Authorization:"Bearer fixture"}}));
  expect(response.status).toBe(200);
  expect(response.headers.get("x-export-owner")).toBe(id);
  expect(response.headers.get("x-export-bytes")).toBe("20");
  expect(response.headers.get("set-cookie")).toBeNull();
  expect(response.headers.get("content-disposition")).toBeNull();
  expect((await GET(new Request("https://fixture.example/api/v1/library/export?owner=other"))).status).toBe(404);
  expect((await POST(new Request("https://fixture.example/api/v1/library/export",{method:"POST"}))).status).toBe(405);
});
