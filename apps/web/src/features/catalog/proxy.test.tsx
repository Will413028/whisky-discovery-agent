import {afterEach, expect, test, vi} from "vitest";
import {GET, POST} from "../../app/api/[...path]/route";

afterEach(() => {vi.unstubAllEnvs(); vi.unstubAllGlobals();});

test("catalog forwards anonymous reads without credentials, cookies or request-selected origin", async () => {
  vi.stubEnv("WHISKY_API_ORIGIN", "http://127.0.0.1:9000");
  const upstream = vi.fn(async (_request: Request) => Response.json({releaseId:null, items:[]}, {
    headers:{"Set-Cookie":"private=value", "Cache-Control":"public,max-age=3600"},
  }));
  vi.stubGlobal("fetch", upstream);
  const result = await GET(new Request("https://web.example/api/v1/catalog", {
    headers:{Authorization:"Bearer ignored", Cookie:"ignored=value", "X-Forwarded-Host":"other.example"},
  }));
  expect(result.status).toBe(200);
  expect(upstream).toHaveBeenCalledOnce();
  const request = upstream.mock.calls[0]?.[0] as Request | undefined;
  expect(request?.url).toBe("http://127.0.0.1:9000/api/v1/catalog");
  expect(request?.headers.get("Authorization")).toBeNull();
  expect(request?.headers.get("Cookie")).toBeNull();
  expect(result.headers.get("Set-Cookie")).toBeNull();
  expect(result.headers.get("Cache-Control")).toBe("no-store");
});

test("catalog does not forward unsupported writes", async () => {
  vi.stubEnv("WHISKY_API_ORIGIN", "http://127.0.0.1:9000");
  const upstream = vi.fn();
  vi.stubGlobal("fetch", upstream);
  expect((await POST(new Request("https://web.example/api/v1/catalog", {method:"POST"}))).status).toBe(405);
  expect(upstream).not.toHaveBeenCalled();
});
