import {expect, test, vi} from "vitest";
import {controlProxy} from "./proxy";

const path = "/api/v1/plans/00000000-0000-4000-8000-000000000001/conditions/patch";

test("partial condition command preserves its immutable retry body through the private proxy", async () => {
  const body = JSON.stringify({key:"fixed-key", expectedRevision:1, baseConditions:{goal:"fruit"}, patch:{budget_twd:"900"}});
  const fetch = vi.fn(async (request: Request) => {
    expect(request.url).toBe(`http://whisky-api.internal${path}`);
    expect(request.method).toBe("POST");
    expect(await request.text()).toBe(body);
    expect(request.headers.get("authorization")).toBe("Bearer synthetic-fixture");
    expect(request.headers.get("cookie")).toBeNull();
    return Response.json({status:"pending"}, {status:202});
  });
  const result = await controlProxy(new Request(`https://web.example${path}`, {method:"POST", headers:{Authorization:"Bearer synthetic-fixture", Cookie:"ignored=value", "Content-Type":"application/json"}, body}), {fetch});
  expect(result.status).toBe(202);
  expect(result.headers.get("cache-control")).toBe("no-store");
  expect(fetch).toHaveBeenCalledOnce();
});

test("partial commands reject alternate method and query before upstream I/O", async () => {
  const fetch = vi.fn();
  expect((await controlProxy(new Request(`https://web.example${path}?other=1`, {method:"POST"}), {fetch})).status).toBe(404);
  expect((await controlProxy(new Request(`https://web.example${path}`), {fetch})).status).toBe(405);
  expect(fetch).not.toHaveBeenCalled();
});
