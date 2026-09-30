import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,expect,test,vi} from "vitest";
import {ResearchStart} from "./ui";

const id="00000000-0000-4000-8000-000000000001";
const push=vi.hoisted(()=>vi.fn());
vi.mock("next/navigation",()=>({useRouter:()=>({push})}));
vi.mock("@auth0/auth0-react",()=>({useAuth0:()=>({isAuthenticated:true,isLoading:false,user:{sub:"fixture"},getAccessTokenSilently:async()=>"fixture"})}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.clearAllMocks();});

test("expert entry preserves the searched name and explicit direction for durable version clarification",async()=>{
  const requests:Request[]=[];
  vi.stubGlobal("fetch",vi.fn(async(input,init)=>{
    const request=new Request(new URL(String(input),window.location.origin),init);
    requests.push(request);
    if(request.url.endsWith("/api/v1/tasks")) return Response.json([]);
    if(request.url.endsWith("/api/v1/plans")) return Response.json({id,conditionsRevision:1});
    const body=await request.clone().json();
    return new Response(`data: ${JSON.stringify({type:"STATE_SNAPSHOT",snapshot:{schemaVersion:1,taskId:id,threadId:body.threadId,conditionsRevision:1,viewVersion:1,status:"queued",stage:"受理",question:null,reportId:null,error:null,observedAt:"2026-10-01T00:00:00Z",activeRunId:body.runId}})}\n\n`,{headers:{"Content-Type":"text/event-stream"}});
  }));
  render(<ResearchStart/>);
  fireEvent.click(screen.getByLabelText("我有喜歡的酒款"));
  fireEvent.change(screen.getByLabelText("喜歡的酒款名稱"),{target:{value:"格蘭菲迪"}});
  fireEvent.change(screen.getByLabelText("探索方向"),{target:{value:"similar"}});
  fireEvent.click(screen.getByRole("button",{name:"開始探索"}));
  await waitFor(()=>expect(push).toHaveBeenCalledWith(`/research/${id}`));
  expect(await requests.find(r=>r.url.endsWith("/api/v1/plans"))?.json()).toMatchObject({conditions:{entry:"expert",starting_bottle:null}});
  expect(await requests.find(r=>r.url.endsWith("/agent"))?.json()).toMatchObject({forwardedProps:{type:"start_v4",input:{phase:"research",sourceText:null,intent:{origin_query:"格蘭菲迪",mode:"similar"}}}});
});

test("a small-step entry preserves the explicitly retained feature and typed exploration target",async()=>{
  const bodies:Record<string,any>[]=[];
  vi.stubGlobal("fetch",vi.fn(async(input,init)=>{
    if(String(input).endsWith("/api/v1/tasks")) return Response.json([]);
    const body=JSON.parse(init.body);bodies.push(body);
    if(String(input).endsWith("/api/v1/plans")) return Response.json({id,conditionsRevision:1});
    return new Response(`data: ${JSON.stringify({type:"STATE_SNAPSHOT",snapshot:{schemaVersion:1,taskId:id,threadId:body.threadId,conditionsRevision:1,viewVersion:1,status:"queued",stage:"受理",question:null,reportId:null,error:null,observedAt:"2026-10-01T00:00:00Z",activeRunId:body.runId}})}\n\n`,{headers:{"Content-Type":"text/event-stream"}});
  }));
  render(<ResearchStart/>);
  fireEvent.click(screen.getByLabelText("我有喜歡的酒款"));
  fireEvent.change(screen.getByLabelText("喜歡的酒款名稱"),{target:{value:"合成起點"}});
  fireEvent.change(screen.getByLabelText("探索方向"),{target:{value:"small_step"}});
  fireEvent.change(screen.getByLabelText("想保留的風味標籤"),{target:{value:"果香"}});
  fireEvent.change(screen.getByLabelText("想嘗試的風味標籤"),{target:{value:"蜂蜜"}});
  fireEvent.click(screen.getByRole("button",{name:"開始探索"}));
  await waitFor(()=>expect(push).toHaveBeenCalledOnce());
  expect(bodies[0].conditions.preferences).toEqual([{description:"果香",intent:"keep",certainty:"user_stated",strength:"soft"}]);
  expect(bodies[1].forwardedProps.input.intent).toMatchObject({mode:"small_step",origin_query:"合成起點",explore_feature:"蜂蜜"});
});

test("contrast is an explicit pair of descriptions, not an inferred smoke-intensity difference",async()=>{
  const bodies:Record<string,any>[]=[];
  vi.stubGlobal("fetch",vi.fn(async(input,init)=>{
    if(String(input).endsWith("/api/v1/tasks")) return Response.json([]);
    const body=JSON.parse(init.body);bodies.push(body);
    if(String(input).endsWith("/api/v1/plans")) return Response.json({id,conditionsRevision:1});
    return new Response(`data: ${JSON.stringify({type:"STATE_SNAPSHOT",snapshot:{schemaVersion:1,taskId:id,threadId:body.threadId,conditionsRevision:1,viewVersion:1,status:"queued",stage:"受理",question:null,reportId:null,error:null,observedAt:"2026-10-01T00:00:00Z",activeRunId:body.runId}})}\n\n`,{headers:{"Content-Type":"text/event-stream"}});
  }));
  render(<ResearchStart/>);
  fireEvent.click(screen.getByLabelText("我有喜歡的酒款"));
  fireEvent.change(screen.getByLabelText("喜歡的酒款名稱"),{target:{value:"合成起點"}});
  fireEvent.change(screen.getByLabelText("探索方向"),{target:{value:"contrast"}});
  fireEvent.change(screen.getByLabelText("起點風味描述"),{target:{value:"蜂蜜"}});
  fireEvent.change(screen.getByLabelText("想對比的風味描述"),{target:{value:"葡萄乾"}});
  fireEvent.click(screen.getByRole("button",{name:"開始探索"}));
  await waitFor(()=>expect(push).toHaveBeenCalledOnce());
  expect(bodies[1].forwardedProps.input.intent).toMatchObject({mode:"contrast",smoke_comparison:false,contrast:{axis:"flavor_description",origin_feature:"蜂蜜",candidate_feature:"葡萄乾"}});
});
