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

it.each([`tasks/${id}?owner=foreign`, "tasks/not-a-uuid", `commands/${id}/extra`])("rejects unsupported read path %s", async path => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  expect((await GET(new Request(`https://web.example/api/v1/${path}`))).status).toBe(404);
  expect(fetcher).not.toHaveBeenCalled();
});

it("rejects mutations on the read endpoints", async () => {
  expect((await POST(new Request(`https://web.example/api/v1/tasks/${id}`, {method: "POST"}))).status).toBe(405);
});
