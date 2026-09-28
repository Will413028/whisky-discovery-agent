import {afterEach, expect, test, vi} from "vitest";
import {controlProxy} from "../src/features/control/proxy";
import {POST} from "../src/app/api/[...path]/route";

const id = "2d9300f8-e5bf-4b02-9325-c94c6b7be9af";

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

test.each([
  [`/api/v1/tasks/${id}/cancel`, "POST"],
  [`/api/v1/plans/${id}/conditions`, "POST"],
  [`/api/v1/plans/${id}/delete`, "POST"],
  ["/api/v1/me/delete", "POST"],
  [`/api/v1/control-commands/${id}`, "GET"],
])("forwards only the typed control endpoint %s %s", async (path, method) => {
  const fetcher = vi.fn(async (_request: Request) => Response.json({status:"pending"}, {status:202, headers:{"set-cookie":"private"}}));
  const response = await controlProxy(new Request(`https://web.example${path}`, {
    method, body:method === "POST" ? '{"key":"once"}' : undefined,
    headers:{authorization:"Bearer fixture", cookie:"private=1", "content-type":"application/json"},
  }), {fetch:fetcher});
  expect(response.status).toBe(202);
  expect(response.headers.get("set-cookie")).toBeNull();
  expect(response.headers.get("cache-control")).toBe("no-store");
  const forwarded = fetcher.mock.calls[0][0];
  expect(forwarded.url).toBe(`http://whisky-api.internal${path}`);
  expect(forwarded.headers.get("authorization")).toBe("Bearer fixture");
  expect(forwarded.headers.get("cookie")).toBeNull();
});

test.each([
  [`/api/v1/tasks/${id}/cancel?upstream=evil`, "POST", 404],
  [`/api/v1/plans/${id}/delete`, "DELETE", 405],
  [`/api/v1/control-commands/${id}`, "POST", 405],
  [`/api/v1/plans/${id}/unknown`, "POST", 404],
  ["/api/v1/me/delete/extra", "POST", 404],
])("rejects unapproved control request %s %s", async (path, method, status) => {
  const fetcher = vi.fn();
  const response = await controlProxy(new Request(`https://web.example${path}`, {method}), {fetch:fetcher});
  expect(response.status).toBe(status);
  expect(fetcher).not.toHaveBeenCalled();
});

test("the catch-all route sends a plan control command to the control adapter", async () => {
  vi.stubEnv("WHISKY_API_ORIGIN", "http://api:8417");
  const fetcher = vi.fn(async (_request: Request) => Response.json({status:"pending"}, {status:202}));
  vi.stubGlobal("fetch", fetcher);
  const response = await POST(new Request(`https://web.example/api/v1/plans/${id}/conditions`, {
    method:"POST", body:'{"key":"once","expectedRevision":1,"conditions":{"entry":"beginner","goal":"果香"}}',
    headers:{authorization:"Bearer fixture", "content-type":"application/json"},
  }));
  expect(response.status).toBe(202);
  expect(fetcher.mock.calls[0][0].url).toBe(`http://api:8417/api/v1/plans/${id}/conditions`);
});
