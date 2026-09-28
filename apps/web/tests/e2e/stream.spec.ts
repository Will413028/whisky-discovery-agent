import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";

test("FastAPI through workerd flushes snapshots before EOF", async ({ page }) => {
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
