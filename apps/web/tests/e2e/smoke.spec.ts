import { expect, test } from "@playwright/test";

test("workerd renders the entry and hydrates its explanation control", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "威士忌探索", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "了解探索方式" }).click();
  await expect(page.getByText("從喜歡的風味或酒款出發，找出下一支想探索的威士忌。", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
