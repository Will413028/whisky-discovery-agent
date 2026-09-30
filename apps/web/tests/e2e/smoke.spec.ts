import { expect, test } from "@playwright/test";

test("public readiness fails closed without its API in Node", async ({request}) => {
  const response = await request.get("/health/ready");
  expect(response.status()).toBe(503);
  expect(response.headers()["cache-control"]).toBe("no-store");
  expect(await response.json()).toEqual({status:"unavailable"});
});

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

test("visitor reaches catalog with the keyboard and sees an honest unavailable state", async ({page}) => {
  const errors:string[]=[];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await page.getByRole("link", {name:"瀏覽已覆核酒款"}).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", {name:"已覆核酒款",level:1})).toBeVisible();
  await expect(page.getByRole("alert").filter({hasText:"暫時無法讀取已覆核酒款"})).toBeVisible();
  await expect(page.getByRole("button", {name:"重新讀取酒款"})).toBeVisible();
  await expect(page.getByText("目前沒有已覆核酒款。")).toHaveCount(0);
  expect(errors).toEqual([]);
});
