import { expect, test } from "@playwright/test";

test("a new login finds unfinished work and answers its saved question", async ({browser, request}) => {
  await request.post("http://127.0.0.1:8419/__research_fixture/reset");
  const context = await browser.newContext();
  const first = await context.newPage();
  const errors: string[] = [];
  first.on("pageerror", error => errors.push(error.message));
  await first.goto("http://127.0.0.1:8419/research");
  await first.getByRole("button", {name:"登入並開始探索"}).click();
  await first.getByLabel("想探索什麼風味？").fill("果香");
  await first.getByRole("button", {name:"開始探索"}).click();
  await expect(first.getByText("你指的是哪個版本？")).toBeVisible();
  const taskUrl = first.url();
  expect(taskUrl).toMatch(/\/research\/[0-9a-f-]{36}$/);
  await first.close();

  const reopened = await context.newPage();
  reopened.on("pageerror", error => errors.push(error.message));
  await reopened.goto("http://127.0.0.1:8419/research");
  await reopened.getByRole("button", {name:"登入並開始探索"}).click();
  const resume = reopened.getByRole("link", {name:"繼續上次探索"});
  await expect(resume).toHaveAttribute("href", new URL(taskUrl).pathname);
  await resume.click();
  await reopened.getByRole("button", {name:"登入查看委託"}).click();
  await expect(reopened.getByText("你指的是哪個版本？")).toBeVisible();
  await reopened.getByLabel("15 年").click();
  await reopened.getByRole("button", {name:"送出答覆"}).click();
  await expect(reopened.getByText("已依補充版本重新查核")).toBeVisible();
  expect(errors).toEqual([]);
  await context.close();
});
