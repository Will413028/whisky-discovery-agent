import {expect, test} from "@playwright/test";

test("synthetic historical direction is explicitly selected and linked to a new research at the current revision",async({page})=>{
  const id="00000000-0000-4000-8000-000000000061";
  const oldTask="00000000-0000-4000-8000-000000000062";
  const nextTask="00000000-0000-4000-8000-000000000063";
  const input={schemaVersion:4,phase:"research",sourceText:null,intent:{mode:"small_step",origin_query:"格蘭菲迪 12 年",explore_feature:"太妃糖",contrast:null,smoke_comparison:false}};
  const commands:Record<string,unknown>[]=[];
  const errors:string[]=[];page.on("pageerror",error=>errors.push(error.message));
  await page.route("**/api/v1/**",async route=>{
    expect(route.request().headers().authorization).toBe("Bearer synthetic-research-token");
    const path=new URL(route.request().url()).pathname;
    if(path===`/api/v1/plans/${id}`) return route.fulfill({json:{id,conditionsRevision:2,conditions:{schema_version:1,entry:"beginner",goal:"目前條件",budget_twd:"900",preferences:[],starting_bottle:null}}});
    if(path===`/api/v1/plans/${id}/tasks`) return route.fulfill({json:{items:[],nextCursor:null}});
    if(path===`/api/v1/plans/${id}/tasks/${oldTask}/restart-context`) return route.fulfill({json:{schemaVersion:4,planId:id,taskId:oldTask,sourceConditionsRevision:1,sourceStartingBottle:null,input}});
    return route.fulfill({status:404,json:{code:"NOT_FOUND"}});
  });
  await page.route("**/agent",async route=>{
    const body=route.request().postDataJSON();commands.push(body);
    if(commands.length===1) return route.fulfill({status:503,json:{code:"TEMPORARY"}});
    const snapshot={schemaVersion:1,taskId:nextTask,threadId:body.threadId,conditionsRevision:2,viewVersion:1,status:"queued",stage:"等待研究開始",question:null,reportId:null,error:null,activeRunId:null,observedAt:"2026-10-01T00:00:00Z"};
    return route.fulfill({contentType:"text/event-stream",body:`data: ${JSON.stringify({type:"STATE_SNAPSHOT",snapshot})}\n\n`});
  });
  await page.goto(`http://127.0.0.1:8419/plans/${id}?restartTaskId=${oldTask}`);
  await page.getByRole("button",{name:"登入查看探索計畫"}).click();
  await expect(page.getByText("沿用來源條件版本 1；新研究使用目前已保存條件。")).toBeVisible();
  const start=page.getByRole("button",{name:"使用已保存條件開始研究"});
  await expect(start).toBeDisabled();expect(commands).toEqual([]);
  await page.getByLabel("沿用這次探索方向").check();
  await expect(page.getByLabel("本次預算上限（新台幣，可留空）")).toHaveValue("900");
  await start.click();
  await expect(page.getByRole("alert")).toContainText("委託暫時無法確認");
  await start.click();
  await expect(page).toHaveURL(new RegExp(`/research/${nextTask}$`));
  expect(commands).toHaveLength(2);expect(commands[1]).toEqual(commands[0]);
  expect(commands[0].forwardedProps).toMatchObject({type:"start_v4",planId:id,conditionsRevision:2,input,sourceTaskId:oldTask});
  expect(errors).toEqual([]);
});

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
  expect(started).toMatchObject({type:"start_v4",planId:id,conditionsRevision:2,input:{phase:"research",sourceText:null}});
  expect(errors).toEqual([]);
});

test("synthetic proposal reopens, confirms only selected preferences, and starts only after the receipt completes",async({page})=>{
  const id="00000000-0000-4000-8000-000000000041";
  const taskId="00000000-0000-4000-8000-000000000042";
  const commandId="00000000-0000-4000-8000-000000000043";
  const nextTaskId="00000000-0000-4000-8000-000000000044";
  const original={schema_version:1,entry:"beginner",goal:"探索果香",budget_twd:"1000",starting_bottle:null,preferences:[]};
  const preference={description:"果香",intent:"prefer",certainty:"user_stated",strength:"soft"};
  let revision=1;
  let submitted:Record<string,unknown>|null=null;
  let started:Record<string,unknown>|null=null;
  const errors:string[]=[];
  page.on("pageerror",error=>errors.push(error.message));
  const task={schemaVersion:1,taskId,threadId:taskId,conditionsRevision:1,viewVersion:3,status:"needs_input",stage:"等待",question:{id:taskId,prompt:"確認偏好",choices:[{id:commandId,label:"保留草稿"}],waitingVersion:1,expiresAt:"2099-10-08T00:00:00Z"},reportId:null,error:null,activeRunId:null,observedAt:"2026-10-01T00:00:00Z"};
  const draft={schemaVersion:4,taskId,planId:id,questionId:taskId,conditionsRevision:1,waitingVersion:1,sourceText:"喜歡水果甜點，預算900",proposal:{summary:"只是線索",intent:{mode:"style_options",smoke_comparison:false},preferences:[{description:"可能喜歡果香",intent:"prefer",source_quote:"喜歡水果甜點",source_kind:"food_clue",certainty:"inferred",strength:"soft",mapping:{feature_key:"果香",reference:{release_id:id,item_id:id},evidence_ids:[id]}}],budget:{action:"set",amount_twd:"900",source_quote:"預算900"}}};
  await page.route("**/api/v1/**",async route=>{
    expect(route.request().headers().authorization).toBe("Bearer synthetic-research-token");
    const path=new URL(route.request().url()).pathname;
    if(path===`/api/v1/tasks/${taskId}`) return route.fulfill({json:task});
    if(path===`/api/v1/tasks/${taskId}/preference-proposal`) return route.fulfill({json:draft});
    if(path===`/api/v1/plans/${id}`) return route.fulfill({json:{id,conditionsRevision:revision,conditions:{...original,preferences:revision===1 ? [] : [preference]}}});
    if(path===`/api/v1/plans/${id}/tasks`) return route.fulfill({json:{items:[],nextCursor:null}});
    if(path.endsWith("/conditions/patch")) {
      submitted=route.request().postDataJSON();
      return route.fulfill({status:202,json:{id:commandId,targetId:id,kind:"plan.change_conditions",status:"intent_confirmed",result:null}});
    }
    if(path===`/api/v1/control-commands/${commandId}`) {
      revision=2;
      return route.fulfill({json:{id:commandId,targetId:id,kind:"plan.change_conditions",status:"completed",result:{conditionsRevision:"2"}}});
    }
    return route.fulfill({status:404,json:{code:"NOT_FOUND"}});
  });
  await page.route("**/agent",async route=>{
    const body=route.request().postDataJSON();started=body.forwardedProps;
    const snapshot={...task,taskId:nextTaskId,threadId:body.threadId,conditionsRevision:2,status:"queued",question:null,viewVersion:1};
    await route.fulfill({contentType:"text/event-stream",body:`data: ${JSON.stringify({type:"RUN_STARTED",threadId:body.threadId,runId:body.runId})}\n\n`+`data: ${JSON.stringify({type:"STATE_SNAPSHOT",snapshot})}\n\n`});
  });
  await page.goto(`http://127.0.0.1:8419/research/${taskId}`);
  await page.getByRole("button",{name:"登入查看委託"}).click();
  await expect(page.getByText("喜歡水果甜點，預算900",{exact:true})).toBeVisible();
  await page.getByRole("link",{name:"到計畫確認偏好與本次預算"}).click();
  await page.getByRole("button",{name:"登入查看探索計畫"}).click();
  await page.getByLabel("確認偏好：可能喜歡果香",{exact:true}).check();
  await page.getByRole("button",{name:"保存指定修改"}).click();
  await expect(page.getByText("變更等待確認；尚未建立新研究。")).toBeVisible();
  expect(submitted).toMatchObject({expectedRevision:1,baseConditions:original,patch:{upsert_preferences:[preference],remove_preferences:[]}});
  expect((submitted as Record<string,unknown>|null)?.patch).not.toHaveProperty("budget_twd");
  expect(started).toBeNull();
  await expect(page.getByRole("button",{name:"使用已保存條件開始研究"})).toBeDisabled();
  await page.getByRole("button",{name:"重新確認變更"}).click();
  await expect(page.getByText("條件版本：2")).toBeVisible();
  await expect(page.getByLabel("本次預算上限（新台幣，可留空）")).toHaveValue("1000");
  await page.getByRole("button",{name:"使用已保存條件開始研究"}).click();
  await expect(page).toHaveURL(new RegExp(`/research/${nextTaskId}$`));
  expect(started).toMatchObject({type:"start_v4",conditionsRevision:2,input:{schemaVersion:4,phase:"research",sourceText:null}});
  expect(errors).toEqual([]);
});

test("synthetic preference editing preserves the budget and applies only explicit changes",async({page})=>{
  const id="00000000-0000-4000-8000-000000000051";
  const commandId="00000000-0000-4000-8000-000000000052";
  const fruit={description:"果香",intent:"keep",certainty:"user_stated",strength:"soft"};
  const honey={description:"蜂蜜",intent:"prefer",certainty:"inferred",strength:"soft"};
  const original={schema_version:1,entry:"beginner",goal:"探索果香",budget_twd:"1000",starting_bottle:null,preferences:[fruit,honey]};
  let revision=1;
  let submitted:Record<string,unknown>|null=null;
  const errors:string[]=[];page.on("pageerror",error=>errors.push(error.message));
  await page.route("**/api/v1/**",async route=>{
    expect(route.request().headers().authorization).toBe("Bearer synthetic-research-token");
    const path=new URL(route.request().url()).pathname;
    if(path===`/api/v1/plans/${id}`) return route.fulfill({json:{id,conditionsRevision:revision,conditions:revision===1 ? original : {...original,preferences:[{...honey,certainty:"user_stated",strength:"hard"}]}}});
    if(path===`/api/v1/plans/${id}/tasks`) return route.fulfill({json:{items:[],nextCursor:null}});
    if(path.endsWith("/conditions/patch")) {
      submitted=route.request().postDataJSON();revision=2;
      return route.fulfill({json:{id:commandId,targetId:id,kind:"plan.change_conditions",status:"completed",result:{conditionsRevision:"2"}}});
    }
    return route.fulfill({status:404,json:{code:"NOT_FOUND"}});
  });
  await page.goto(`http://127.0.0.1:8419/plans/${id}`);
  await page.getByRole("button",{name:"登入查看探索計畫"}).click();
  await page.getByRole("button",{name:"移除偏好：果香"}).click();
  await page.getByLabel("蜂蜜設為硬限制").check();
  await page.getByRole("button",{name:"保存指定修改"}).click();
  await expect(page.getByText("條件版本：2")).toBeVisible();
  expect(submitted).toMatchObject({expectedRevision:1,baseConditions:original,patch:{upsert_preferences:[{...honey,certainty:"user_stated",strength:"hard"}],remove_preferences:["果香"]}});
  expect((submitted as Record<string,unknown>|null)?.patch).not.toHaveProperty("budget_twd");
  await expect(page.getByLabel("本次預算上限（新台幣，可留空）")).toHaveValue("1000");
  await expect(page.getByRole("button",{name:"移除偏好：果香"})).toHaveCount(0);
  await expect(page.getByLabel("蜂蜜設為硬限制")).toBeChecked();
  expect(errors).toEqual([]);
});
