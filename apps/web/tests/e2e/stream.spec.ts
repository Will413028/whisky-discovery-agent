import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";

test("browser reconnects observation after EOF and logout stops further requests", async ({ page }) => {
  const errors: string[] = [];
  const requests: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {if (request.url().endsWith("/agent/observe")) requests.push(request.postData() ?? "");});
  await page.goto("http://127.0.0.1:3420/?reconnect=1");
  await expect(page.locator("output")).toContainText('"connection":2');
  await expect(page.locator("output")).toContainText('"stopped":true');
  const result = JSON.parse(await page.locator("output").innerText());
  expect(result.status).toBe("needs_input");
  expect(result.version).toBe(2);
  expect(result.tokens).toBe(2);
  expect(requests).toHaveLength(2);
  expect(requests.map(body=>JSON.parse(body).conditionsRevision)).toEqual([1, 1]);
  expect(errors).toEqual([]);
});

test("FastAPI through Node and workerd flushes snapshots before EOF", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("http://127.0.0.1:3420/");
  await expect(page.locator("output")).toContainText("needs_input");
  const result = JSON.parse(await page.locator("output").innerText());
  const timing = test.info().outputPath("stream-timing.json");
  await writeFile(timing, JSON.stringify(result, null, 2));
  await test.info().attach("stream-timing", {path:timing, contentType:"application/json"});
  expect(result.connected).toBe(false);
  expect(result.times).toHaveLength(2);
  expect(result.times[1] - result.times[0]).toBeGreaterThan(400);
  expect(errors).toEqual([]);
});
