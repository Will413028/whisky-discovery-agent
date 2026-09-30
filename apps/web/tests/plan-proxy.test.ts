import {describe, expect, it, vi} from "vitest";
import {planProxy} from "../src/features/discovery/proxy";

const id = "2d9300f8-e5bf-4b02-9325-c94c6b7be9af";

describe("plan API proxy", () => {
  it("forwards owned history pagination and never allows history mutation", async () => {
    let received:Request | undefined;
    const fetcher = vi.fn(async (request:Request) => {received=request; return Response.json({items:[],nextCursor:null});});
    const path = `https://web.example/api/v1/plans/${id}/tasks?limit=1&cursor=YWJjZA%3D%3D`;
    expect((await planProxy(new Request(path),{fetch:fetcher})).status).toBe(200);
    expect(received?.url).toBe(`http://whisky-api.internal/api/v1/plans/${id}/tasks?limit=1&cursor=YWJjZA%3D%3D`);
    expect((await planProxy(new Request(path.split("?")[0],{method:"POST"}),{fetch:fetcher})).status).toBe(405);
    expect(fetcher).toHaveBeenCalledOnce();
  });
  it("preserves approved pagination through the configured Node upstream", async () => {
    const {apiUpstream} = await import("../src/shared/api/upstream.server");
    let forwarded: Request | undefined;
    const upstream = apiUpstream("http://api:8417", async request => {
      forwarded = request;
      return Response.json({items: [], nextCursor: null});
    });
    const response = await planProxy(new Request("https://web.example/api/v1/plans?limit=2&cursor=YWJjZA%3D%3D"), upstream);
    expect(response.status).toBe(200);
    expect(forwarded?.url).toBe("http://api:8417/api/v1/plans?limit=2&cursor=YWJjZA%3D%3D");
  });

  it.each(["limit=0", "limit=51", "limit=bad", "limit=1&limit=2", "cursor=", "cursor=bad!", "cursor=x&cursor=y"])("rejects invalid pagination: %s", async query => {
    const fetcher = vi.fn();
    const response = await planProxy(new Request(`https://web.example/api/v1/plans?${query}`), {fetch: fetcher});
    expect(response.status).toBe(422);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("forwards the JSON command to a fixed origin with only required headers", async () => {
    const body = JSON.stringify({key: "fixture", conditions: {entry: "beginner", goal: "果香"}});
    let received: Request | undefined;
    let receivedBody: string | undefined;
    const fetcher = vi.fn(async (request: Request) => {
      received = request;
      receivedBody = await request.text();
      return Response.json({id}, {status: 201, headers: {"set-cookie": "upstream-private=1"}});
    });
    const response = await planProxy(new Request("https://web.example/api/v1/plans", {
      method: "POST", body, headers: {"content-type": "application/json", authorization: "Bearer fixture", cookie: "private=1", "x-owner-id": "untrusted"},
    }), {fetch: fetcher});
    expect(response.status).toBe(201);
    expect(received?.url).toBe("http://whisky-api.internal/api/v1/plans");
    expect(received?.method).toBe("POST");
    expect(receivedBody).toBe(body);
    expect(received?.headers.get("authorization")).toBe("Bearer fixture");
    expect(received?.headers.get("cookie")).toBeNull();
    expect(received?.headers.get("x-owner-id")).toBeNull();
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it("allows only GET on a concrete plan resource", async () => {
    const fetcher = vi.fn(async () => Response.json({id}));
    expect((await planProxy(new Request(`https://web.example/api/v1/plans/${id}`), {fetch: fetcher})).status).toBe(200);
    expect((await planProxy(new Request(`https://web.example/api/v1/plans/${id}`, {method: "DELETE"}), {fetch: fetcher})).status).toBe(405);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it.each(["/api/v1/plans?upstream=https://evil.example", "/api/v1/plans/not-a-uuid", "/api/v1/plans/../me", "/api/v1/actors/" + id])("rejects an unapproved path: %s", async path => {
    const fetcher = vi.fn();
    expect((await planProxy(new Request(`https://web.example${path}`), {fetch: fetcher})).status).toBe(404);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("does not follow an upstream redirect", async () => {
    const response = await planProxy(new Request(`https://web.example/api/v1/plans/${id}`), {
      fetch: async () => new Response(null, {status: 302, headers: {location: "https://other.example"}}),
    });
    expect(response.status).toBe(502);
    expect(response.headers.get("location")).toBeNull();
  });
});
