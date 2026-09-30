import {expect, test} from "@playwright/test";

test("synthetic history reopens revision one after the plan has moved to revision two", async ({page}) => {
  const id="00000000-0000-4000-8000-000000000031";
  const taskId="00000000-0000-4000-8000-000000000032";
  const reportId="00000000-0000-4000-8000-000000000033";
  const task={schemaVersion:1,taskId,threadId:taskId,conditionsRevision:1,viewVersion:2,status:"completed",stage:"完成",question:null,reportId,error:null,activeRunId:null,observedAt:"2026-09-30T00:00:00Z"};
  const errors:string[]=[];
  page.on("pageerror",error=>errors.push(error.message));
  await page.route("**/api/v1/**",async route=>{
    const path=new URL(route.request().url()).pathname;
    expect(route.request().headers().authorization).toBe("Bearer synthetic-research-token");
    if(path===`/api/v1/plans/${id}`) return route.fulfill({json:{id,conditionsRevision:2,conditions:{schema_version:1,entry:"beginner",goal:"改為探索甜香",budget_twd:"900",preferences:[],starting_bottle:null}}});
    if(path===`/api/v1/plans/${id}/tasks`) return route.fulfill({json:{items:[{task,createdAt:"2026-09-29T00:00:00Z"}],nextCursor:null}});
    if(path===`/api/v1/tasks/${taskId}`) return route.fulfill({json:task});
    if(path===`/api/v1/reports/${reportId}`) return route.fulfill({json:{id:reportId,taskId,summary:"合成歷史報告：原條件果香",candidates:[]}});
    return route.fulfill({status:404,json:{code:"NOT_FOUND"}});
  });
  await page.goto(`http://127.0.0.1:8419/plans/${id}`);
  await page.getByRole("button",{name:"登入查看探索計畫"}).click();
  await expect(page.getByText("條件版本：2")).toBeVisible();
  await expect(page.getByText("歷史條件版本 1")).toBeVisible();
  await expect(page.locator("time")).toHaveAttribute("datetime","2026-09-29T00:00:00Z");
  await page.getByRole("link",{name:"查看研究 completed"}).click();
  await page.getByRole("button",{name:"登入查看委託"}).click();
  await expect(page.getByText("合成歷史報告：原條件果香")).toBeVisible();
  await expect(page.getByText("此報告採用條件版本 1；修改條件後需另開研究。")).toBeVisible();
  expect(errors).toEqual([]);
});

test("synthetic browser reopens a saved plan, confirms one partial edit, and explicitly starts its new revision", async ({page}) => {
  const id = "00000000-0000-4000-8000-000000000021";
  const commandId = "00000000-0000-4000-8000-000000000022";
  const taskId = "00000000-0000-4000-8000-000000000023";
  const original = {schema_version:1,entry:"beginner",goal:"保留果香",budget_twd:"1000",starting_bottle:null,preferences:[]};
  let plan = {id,conditionsRevision:1,conditions:original};
  let bodies: unknown[] = [];
  let started: Record<string, unknown> | null = null;
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/v1/**", async route => {
    expect(route.request().headers().authorization).toBe("Bearer synthetic-research-token");
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/plans") return route.fulfill({json:{items:[plan],nextCursor:null}});
    if (path === `/api/v1/plans/${id}`) return route.fulfill({json:plan});
    if (path === `/api/v1/plans/${id}/tasks`) return route.fulfill({json:{items:[],nextCursor:null}});
    if (path.endsWith("/conditions/patch")) {
      bodies.push(route.request().postDataJSON());
      if (bodies.length === 1) return route.fulfill({status:503,json:{code:"REQUEST_FAILED"}});
      if (bodies.length === 2) return route.fulfill({status:202,json:{id:commandId,targetId:id,kind:"plan.change_conditions",status:"pending",result:null}});
      plan = {...plan,conditionsRevision:2,conditions:{...original,budget_twd:"900"}};
      return route.fulfill({json:{id:commandId,targetId:id,kind:"plan.change_conditions",status:"completed",result:{conditionsRevision:"2"}}});
    }
    return route.fulfill({status:404,json:{code:"NOT_FOUND"}});
  });
  await page.route("**/agent", async route => {
    const body = route.request().postDataJSON();
    started = body.forwardedProps;
    const snapshot = {schemaVersion:1,taskId,threadId:body.threadId,conditionsRevision:2,viewVersion:1,status:"queued",stage:"等待研究開始",question:null,reportId:null,error:null,activeRunId:null,observedAt:"2026-09-30T00:00:00Z"};
    await route.fulfill({contentType:"text/event-stream",body:
      `data: ${JSON.stringify({type:"RUN_STARTED",threadId:body.threadId,runId:body.runId})}\n\n` +
      `data: ${JSON.stringify({type:"STATE_SNAPSHOT",snapshot})}\n\n`});
  });
  await page.goto("http://127.0.0.1:8419/plans");
  await page.getByRole("button", {name:"登入查看探索計畫"}).click();
  await page.getByRole("link", {name:"保留果香"}).click();
  await page.getByRole("button", {name:"登入查看探索計畫"}).click();
  await expect(page.getByLabel("本次探索目標")).toHaveValue("保留果香");
  await page.getByLabel("本次預算上限（新台幣，可留空）").fill("900");
  await page.getByRole("button", {name:"保存指定修改"}).click();
  await expect(page.getByRole("alert")).toContainText("變更暫時無法確認");
  await page.getByRole("button", {name:"重試同一變更"}).click();
  await expect(page.getByText("變更等待確認；尚未建立新研究。")).toBeVisible();
  await expect(page.getByRole("button", {name:"使用已保存條件開始研究"})).toBeDisabled();
  expect(bodies[1]).toEqual(bodies[0]);
  expect(bodies[0]).toMatchObject({expectedRevision:1,baseConditions:original,patch:{budget_twd:"900"}});
  expect(started).toBeNull();
  await page.getByRole("button", {name:"重新確認變更"}).click();
  await expect(page.getByText("條件版本：2")).toBeVisible();
  expect(bodies).toHaveLength(3);
  expect(bodies[2]).toEqual(bodies[0]);
  await expect(page.getByLabel("本次探索目標")).toHaveValue("保留果香");
  await page.getByRole("button", {name:"使用已保存條件開始研究"}).click();
  await expect(page).toHaveURL(new RegExp(`/research/${taskId}$`));
  expect(started).toMatchObject({type:"start",planId:id,conditionsRevision:2});
  expect(errors).toEqual([]);
});
