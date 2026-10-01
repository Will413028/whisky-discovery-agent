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
