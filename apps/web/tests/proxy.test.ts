// @vitest-environment node
import { expect, test, vi } from "vitest";
import { proxy } from "../src/features/identity/proxy";

test("forwards the allowed request to a fixed private upstream", async () => {
  const fetch = vi.fn(async (_request: Request) => Response.json({ id: "fixture" }));
  const response = await proxy(new Request("https://web.example/api/v1/me", { headers: { Authorization: "Bearer fixture", Cookie: "private-cookie" } }), { fetch });
  expect(response.status).toBe(200);
  const forwarded = fetch.mock.calls[0][0];
  expect(forwarded.url).toBe("http://whisky-api.internal/api/v1/me");
  expect(forwarded.headers.get("authorization")).toBe("Bearer fixture");
  expect(forwarded.headers.has("cookie")).toBe(false);
  expect(response.headers.get("cache-control")).toBe("no-store");
});

test.each([
  ["/api/v1/me?upstream=https://evil.example", "GET", 404],
  ["/api/v1/unknown", "GET", 404],
  ["/api/v1/me", "POST", 405],
])("blocks unapproved proxy request %s %s", async (path, method, status) => {
  const fetch = vi.fn();
  const response = await proxy(new Request(`https://web.example${path}`, { method }), { fetch });
  expect(response.status).toBe(status);
  expect(fetch).not.toHaveBeenCalled();
  expect(response.headers.get("cache-control")).toBe("no-store");
});

test("does not follow or reveal upstream redirects", async () => {
  const response = await proxy(new Request("https://web.example/api/v1/me"), {
    fetch: async () => new Response(null, { status: 302, headers: { location: "https://evil.example", "set-cookie": "private" } }),
  });
  expect(response.status).toBe(502);
  expect(response.headers.has("location")).toBe(false);
  expect(response.headers.has("set-cookie")).toBe(false);
});
