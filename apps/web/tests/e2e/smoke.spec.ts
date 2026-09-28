import { expect, test } from "@playwright/test";

test("observe route fails closed without a private API origin in Node", async ({ request }) => {
  const response = await request.post("/agent/observe", {data:{taskId:crypto.randomUUID(), runId:crypto.randomUUID(), conditionsRevision:1}});
  expect(response.status()).toBe(503);
  expect(response.headers()["cache-control"]).toBe("no-store");
  expect((await response.json()).code).toBe("PROXY_UNAVAILABLE");
});

test("Node renders the entry and hydrates its explanation control", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "威士忌探索", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "了解探索方式" }).click();
  await expect(page.getByText("從喜歡的風味或酒款出發，找出下一支想探索的威士忌。", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("unconfigured identity stays closed in Node", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/account");
  await expect(page.getByText("帳號功能準備中。")).toBeVisible();
  const response = await request.get("/api/v1/me");
  expect(response.status()).toBe(503);
  expect(response.headers()["cache-control"]).toBe("no-store");
  expect((await response.json()).code).toBe("PROXY_UNAVAILABLE");
  expect(errors).toEqual([]);
});
