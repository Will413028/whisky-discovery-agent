import { expect, test, vi } from "vitest";
import { apiUpstream } from "../src/shared/api/upstream.server";

test("Node upstream uses only configured origin and preserves streaming cancellation", async () => {
  const fetcher=vi.fn(async(_request: Request)=>new Response("data: test\n\n"));
  const upstream=apiUpstream("http://api:8417",fetcher);
  expect(upstream).toBeDefined();
  const abort=new AbortController();
  const request=new Request("http://whisky-api.internal/agent/observe", {
    method:"POST",body:'{"taskId":"synthetic"}',headers:{Authorization:"Bearer synthetic"},
    signal:abort.signal,redirect:"manual",
  });
  const response=await upstream!.fetch(request);
  const forwarded=fetcher.mock.calls[0]![0] as Request;
  expect(forwarded.url).toBe("http://api:8417/agent/observe");
  expect(forwarded.method).toBe("POST");
  expect(forwarded.headers.get("authorization")).toBe("Bearer synthetic");
  expect(forwarded.redirect).toBe("manual");
  expect(await forwarded.text()).toBe('{"taskId":"synthetic"}');
  abort.abort();
  expect(forwarded.signal.aborted).toBe(true);
  expect(await response.text()).toBe("data: test\n\n");
});

test("unconfigured or malformed API origin stays closed", () => {
  expect(apiUpstream(undefined)).toBeUndefined();
  for (const origin of ["https://api/path","http://user:password@api", "http://api?target=other", "file:///tmp/api"]) {
    expect(()=>apiUpstream(origin)).toThrow();
  }
});

test("Node upstream preserves an already validated pagination query", async () => {
  const fetcher = vi.fn(async (_request: Request) => Response.json({items: []}));
  await apiUpstream("http://api:8417", fetcher)!.fetch(
    new Request("http://whisky-api.internal/api/v1/plans?limit=2&cursor=YWJjZA%3D%3D"),
  );
  expect(fetcher.mock.calls[0][0].url).toBe("http://api:8417/api/v1/plans?limit=2&cursor=YWJjZA%3D%3D");
});
