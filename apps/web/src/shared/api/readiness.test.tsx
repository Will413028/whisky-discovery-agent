import {describe, expect, it} from "vitest";
import {readinessProbe} from "./readiness";

describe("public readiness", () => {
  it("fails closed without the fixed API connection", async () => {
    const result = await readinessProbe();
    expect(result.status).toBe(503);
    expect(result.headers.get("Cache-Control")).toBe("no-store");
    expect(await result.json()).toEqual({status: "unavailable"});
  });

  it("checks only API readiness and never exposes its body", async () => {
    let seen: Request | undefined;
    const result = await readinessProbe({fetch: async request => {
      seen = request;
      return Response.json({status: "ok", internal: "private-detail"});
    }});
    expect(seen?.url).toBe("http://whisky-api.internal/health/ready");
    expect(seen?.method).toBe("GET");
    expect([...seen!.headers]).toEqual([]);
    expect(seen?.redirect).toBe("manual");
    expect(seen?.signal).toBeDefined();
    expect(result.status).toBe(200);
    expect(await result.json()).toEqual({status: "ok"});
  });

  it.each([301, 401, 503])("rejects upstream status %s", async status => {
    const result = await readinessProbe({fetch: async () => new Response("detail", {status})});
    expect(result.status).toBe(503);
    expect(await result.json()).toEqual({status: "unavailable"});
  });

  it("returns unavailable on connection failure", async () => {
    const result = await readinessProbe({fetch: async () => {throw new Error("private host detail");}});
    expect(result.status).toBe(503);
    expect(await result.json()).toEqual({status: "unavailable"});
  });
});
