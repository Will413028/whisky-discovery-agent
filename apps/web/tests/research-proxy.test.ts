// @vitest-environment node
import { expect, test, vi } from "vitest";
import { researchStreamProxy } from "../src/features/research/proxy";

test("observe proxy forwards bearer and body only to its fixed upstream", async () => {
  const fetch = vi.fn(async (_request: Request) => new Response('data: {}\n\n', {headers:{"Content-Type":"text/event-stream", "Set-Cookie":"private", "Cache-Control":"public"}}));
  const response = await researchStreamProxy(new Request("https://fixture.example/agent/observe", {method:"POST", body:'{"taskId":"fixture"}', headers:{Authorization:"Bearer fixture", Cookie:"private=1", "Content-Type":"application/json"}}), {fetch});
  const forwarded = fetch.mock.calls[0][0] as Request;
  expect(forwarded.url).toBe("http://whisky-api.internal/agent/observe");
  expect(forwarded.headers.get("authorization")).toBe("Bearer fixture");
  expect(forwarded.headers.has("cookie")).toBe(false);
  expect(await forwarded.text()).toBe('{"taskId":"fixture"}');
  expect(response.headers.get("cache-control")).toBe("no-store");
  expect(response.headers.has("set-cookie")).toBe(false);
});

test.each([
  ["/agent/observe?upstream=other", "POST", 404],
  ["/agent/start", "POST", 404],
  ["/agent/observe", "GET", 405],
])("rejects non-allowlisted %s %s", async (path, method, status) => {
  const fetch = vi.fn(async () => new Response());
  const response = await researchStreamProxy(new Request(`https://fixture.example${path}`, {method}), {fetch});
  expect(response.status).toBe(status);
  expect(fetch).not.toHaveBeenCalled();
});

test("an upstream redirect cannot expose a different location", async () => {
  const response = await researchStreamProxy(new Request("https://fixture.example/agent/observe", {method:"POST"}), {
    fetch:async () => new Response(null, {status:302, headers:{Location:"https://other.example/private"}}),
  });
  expect(response.status).toBe(502);
  expect(response.headers.has("location")).toBe(false);
});

test("agent start streams through the fixed API and exposes its command receipt", async () => {
  const fetch = vi.fn(async (_request: Request) => new Response('data: {}\n\n', {headers: {"Content-Type": "text/event-stream", "X-Command-Id": "receipt", "Set-Cookie": "private"}}));
  const response = await researchStreamProxy(new Request("https://fixture.example/agent", {method: "POST", body: '{"forwardedProps":{"type":"start"}}'}), {fetch});
  expect(response.status).toBe(200);
  expect(fetch.mock.calls[0][0].url).toBe("http://whisky-api.internal/agent");
  expect(response.headers.get("x-command-id")).toBe("receipt");
  expect(response.headers.has("set-cookie")).toBe(false);
});
