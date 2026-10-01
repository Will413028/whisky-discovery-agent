import {expect,test,type Page} from "@playwright/test";

test("synthetic favorite retries one command and reopens without becoming a tasting preference",async({browser})=>{
  const context=await browser.newContext();
  const id="00000000-0000-4000-8000-000000000001";
  let saved:Record<string,unknown>={schemaVersion:1,id,bottleVersionId:id,revision:1,wantToExplore:true,tasting:"not_tasted",tastingReason:"",createdAt:"2026-10-01T00:00:00Z",updatedAt:"2026-10-01T00:00:00Z"};
  const commands:unknown[]=[];
  let loseFirst=true;
  async function fixtures(page:Page){
    await page.route("**/api/v1/catalog",route=>route.fulfill({json:{releaseId:null,evaluatedOn:"2026-10-01",pricePolicyVersion:"synthetic",items:[]}}));
    await page.route("**/api/v1/library/feedback**",async route=>{
      const request=route.request();
      if(request.method()==="POST"){
        const command=request.postDataJSON();commands.push(command);
        saved={schemaVersion:1,id,bottleVersionId:id,revision:command.expectedRevision+1,wantToExplore:command.wantToExplore,tasting:command.tasting,tastingReason:command.tastingReason,createdAt:"2026-10-01T00:00:00Z",updatedAt:"2026-10-01T00:00:00Z"};
        if(loseFirst){loseFirst=false;await route.abort();return;}
        await route.fulfill({status:201,json:saved});return;
      }
      if(new URL(request.url()).pathname.endsWith(id)){
        await route.fulfill({json:saved});return;
      }
      await route.fulfill({json:{schemaVersion:1,items:[saved],nextCursor:null}});
    });
  }
  const first=await context.newPage();await fixtures(first);
  await first.goto("http://127.0.0.1:8419/research?library=1");
  await first.getByRole("button",{name:"登入查看收藏與品飲回饋"}).click();
  await first.getByLabel("想探索（收藏）").check();
  await expect(first.getByLabel("品飲感受")).toHaveValue("not_tasted");
  await first.getByRole("button",{name:"保存酒款回饋"}).click();
  await first.getByRole("button",{name:"重送同一回饋"}).click();
  await expect(first.getByText("酒款回饋已保存。")).toBeVisible();
  expect(commands).toHaveLength(2);expect(commands[0]).toEqual(commands[1]);
  await first.close();
  const reopened=await context.newPage();await fixtures(reopened);
  await reopened.goto("http://127.0.0.1:8419/research?library=1");
  await reopened.getByRole("button",{name:"登入查看收藏與品飲回饋"}).click();
  await expect(reopened.getByLabel("想探索（收藏）")).toBeChecked();
  await expect(reopened.getByLabel("品飲感受")).toHaveValue("not_tasted");
  await expect(reopened.getByText(/目前庫內無法解析此版本/)).toBeVisible();
  await context.close();
});

test("synthetic explicit preferences reopen and apply only after selection in a new exploration",async({browser})=>{
  const context=await browser.newContext();
  let profile={schemaVersion:1,revision:0,preferences:[] as unknown[],updatedAt:null as string|null};
  const plans:Record<string,unknown>[]=[];
  async function fixtures(page:Page){
    await page.route("**/api/v1/library/preferences",async route=>{
      if(route.request().method()==="POST"){
        const command=route.request().postDataJSON();
        profile={schemaVersion:1,revision:command.expectedRevision+1,preferences:command.preferences,updatedAt:"2026-10-01T00:00:00Z"};
        await route.fulfill({status:201,json:profile});return;
      }
      await route.fulfill({json:profile});
    });
    await page.route("**/api/v1/library/feedback",route=>route.fulfill({json:{schemaVersion:1,items:[],nextCursor:null}}));
    await page.route("**/api/v1/catalog",route=>route.fulfill({json:{releaseId:null,evaluatedOn:"2026-10-01",pricePolicyVersion:"synthetic",items:[]}}));
    await page.route("**/api/v1/plans",async route=>{
      if(route.request().method()==="POST")plans.push(route.request().postDataJSON());
      await route.continue();
    });
  }
  const first=await context.newPage();await fixtures(first);
  await first.goto("http://127.0.0.1:8419/research?library=1");
  await first.getByRole("button",{name:"登入查看收藏與品飲回饋"}).click();
  await first.getByLabel("偏好特徵").fill("果香");
  await first.getByLabel("我的明確陳述").fill("合成驗收：我明確喜歡果香");
  await first.getByRole("button",{name:"加入明確偏好"}).click();
  await first.getByRole("button",{name:"保存長期偏好"}).click();
  await expect(first.getByText("長期偏好已保存。")).toBeVisible();
  await first.close();
  const next=await context.newPage();await fixtures(next);
  await next.goto("http://127.0.0.1:8419/research?library=1");
  await next.getByRole("button",{name:"登入查看收藏與品飲回饋"}).click();
  await expect(next.getByText("合成驗收：我明確喜歡果香")).toBeVisible();
  await next.goto("http://127.0.0.1:8419/research");
  await next.getByRole("button",{name:"登入並開始探索"}).click();
  await expect(next.getByLabel("套用 果香")).not.toBeChecked();
  await next.getByLabel("套用 果香").check();
  await next.getByLabel("想探索什麼風味？").fill("合成驗收：想看看有來源的選擇");
  await next.getByRole("button",{name:"開始探索"}).click();
  await expect.poll(()=>plans.length).toBe(1);
  const conditions=plans[0].conditions as Record<string,unknown>;
  expect(conditions.preferences).toEqual([{description:"果香",intent:"prefer",certainty:"user_stated",strength:"soft"}]);
  expect(conditions.budget_twd).toBeNull();
  await context.close();
});
