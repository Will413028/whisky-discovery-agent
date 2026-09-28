import {afterEach, expect, it, vi} from "vitest";
import {GET, POST} from "../src/app/api/[...path]/route";

const id = "2d9300f8-e5bf-4b02-9325-c94c6b7be9af";
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it.each(["tasks", "commands", "reports"])("forwards owner-authenticated %s reads to the fixed API", async resource => {
  vi.stubEnv("WHISKY_API_ORIGIN", "http://api:8417");
  const fetcher = vi.fn(async (_request: Request) => Response.json({id}));
  vi.stubGlobal("fetch", fetcher);
  const response = await GET(new Request(`https://web.example/api/v1/${resource}/${id}`, {
    headers: {Authorization: "Bearer fixture", Cookie: "private=value"},
  }));
  expect(response.status).toBe(200);
  expect(response.headers.get("cache-control")).toBe("no-store");
  const request = fetcher.mock.calls[0][0];
  expect(request.url).toBe(`http://api:8417/api/v1/${resource}/${id}`);
  expect(request.headers.get("authorization")).toBe("Bearer fixture");
  expect(request.headers.get("cookie")).toBeNull();
});

it("forwards the unfinished task list with owner auth and no cookies", async () => {
  vi.stubEnv("WHISKY_API_ORIGIN", "http://api:8417");
  const fetcher = vi.fn(async (_request: Request) => Response.json([]));
  vi.stubGlobal("fetch", fetcher);
  const response = await GET(new Request("https://web.example/api/v1/tasks", {
    headers:{Authorization:"Bearer fixture",Cookie:"private=value"},
  }));
  expect(response.status).toBe(200);
  const forwarded = fetcher.mock.calls[0][0] as Request;
  expect(forwarded.url).toBe("http://api:8417/api/v1/tasks");
  expect(forwarded.headers.get("authorization")).toBe("Bearer fixture");
  expect(forwarded.headers.get("cookie")).toBeNull();
});

it.each([`tasks/${id}?owner=foreign`, "tasks/not-a-uuid", `commands/${id}/extra`])("rejects unsupported read path %s", async path => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  expect((await GET(new Request(`https://web.example/api/v1/${path}`))).status).toBe(404);
  expect(fetcher).not.toHaveBeenCalled();
});

it("rejects mutations on the read endpoints", async () => {
  expect((await POST(new Request(`https://web.example/api/v1/tasks/${id}`, {method: "POST"}))).status).toBe(405);
});

it("forwards only the scoped clarification answer mutation without cookies", async () => {
  vi.stubEnv("WHISKY_API_ORIGIN", "http://api:8417");
  const fetcher = vi.fn(async (_request: Request) => Response.json({id, taskId:id, scope:"research.answer", acceptance:"accepted"}));
  vi.stubGlobal("fetch", fetcher);
  const path = `/api/v1/tasks/${id}/clarifications/${id}/answer`;
  const response = await POST(new Request(`https://web.example${path}`, {
    method:"POST", headers:{Authorization:"Bearer fixture", Cookie:"private=value", "Content-Type":"application/json"},
    body:JSON.stringify({key:"answer-key", conditionsRevision:1, waitingVersion:1, answer:"15 年"}),
  }));
  expect(response.status).toBe(200);
  expect(response.headers.get("cache-control")).toBe("no-store");
  const forwarded = fetcher.mock.calls[0][0];
  expect(forwarded.url).toBe(`http://api:8417${path}`);
  expect(forwarded.headers.get("authorization")).toBe("Bearer fixture");
  expect(forwarded.headers.get("cookie")).toBeNull();
  expect(await forwarded.json()).toEqual({key:"answer-key", conditionsRevision:1, waitingVersion:1, answer:"15 年"});
  expect((await POST(new Request(`https://web.example${path}?owner=other`, {method:"POST"}))).status).toBe(404);
  expect((await GET(new Request(`https://web.example${path}`))).status).toBe(405);
});
