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

test("FastAPI through Node and workerd flushes the first snapshot before release", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("http://127.0.0.1:3420/?gated=1");
  await expect(page.locator("output")).toContainText('"status":"researching"');
  const first = JSON.parse(await page.locator("output").innerText());
  expect(first).toMatchObject({connected:true, snapshots:1});
  const released = await request.post("http://127.0.0.1:8419/__release");
  expect(released.ok()).toBe(true);
  await expect(page.locator("output")).toContainText("needs_input");
  const result = JSON.parse(await page.locator("output").innerText());
  const timing = test.info().outputPath("stream-timing.json");
  await writeFile(timing, JSON.stringify(result, null, 2));
  await test.info().attach("stream-timing", {path:timing, contentType:"application/json"});
  expect(result.connected).toBe(false);
  expect(result.snapshots).toBe(2);
  expect(errors).toEqual([]);
});
