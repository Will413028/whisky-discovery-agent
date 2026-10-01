import {expect,test,vi} from "vitest";
import edge from "../../edge/src/index";

test("thin edge preserves the public origin and streams through its fixed web binding", async()=>{
  let close!:()=>void;
  const body=new ReadableStream<Uint8Array>({start(controller){
    controller.enqueue(new TextEncoder().encode("data: first\n\n"));
    close=()=>controller.close();
  }});
  const fetcher=vi.fn(async(_request:Request)=>new Response(body,{headers:{"Content-Type":"text/event-stream","Cache-Control":"no-store"}}));
  const abort=new AbortController();
  const response=await edge.fetch(new Request("https://whisky.example/agent/observe",{
    method:"POST",body:"synthetic",signal:abort.signal,
    headers:{Authorization:"Bearer synthetic","X-Forwarded-Host":"attacker.invalid","X-Forwarded-Proto":"http"},
  }),{WHISKY_WEB:{fetch:fetcher}});
  expect(response.status).toBe(200);
  const forwarded=fetcher.mock.calls[0]![0];
  expect(forwarded.url).toBe("http://whisky-web.internal/agent/observe");
  expect(forwarded.headers.get("x-forwarded-host")).toBe("whisky.example");
  expect(forwarded.headers.get("x-forwarded-proto")).toBe("https");
  expect(forwarded.headers.get("authorization")).toBe("Bearer synthetic");
  expect(forwarded.redirect).toBe("manual");
  expect(forwarded.method).toBe("POST");
  expect(await forwarded.text()).toBe("synthetic");
  const reader=response.body!.getReader();
  expect(new TextDecoder().decode((await reader.read()).value)).toBe("data: first\n\n");
  expect(response.headers.get("cache-control")).toBe("no-store");
  abort.abort();
  expect(forwarded.signal.aborted).toBe(true);
  close();
});

test("edge failures are safe and never cache private failures",async()=>{
  for (const binding of [undefined,{fetch:async()=>{throw new Error("private VM detail");}}]) {
    const response=await edge.fetch(new Request("https://whisky.example/api/v1/me"),{WHISKY_WEB:binding});
    expect(response.status).toBe(503);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.text()).not.toContain("private VM detail");
  }
});

test("only account export survives preparation past the ordinary edge deadline",async()=>{
  vi.useFakeTimers();
  vi.spyOn(AbortSignal,"timeout").mockImplementation(milliseconds=>{
    const controller=new AbortController();
    setTimeout(()=>controller.abort(),milliseconds);
    return controller.signal;
  });
  try {
    const binding={fetch:(request:Request)=>new Promise<Response>((resolve,reject)=>{
      request.signal.addEventListener("abort",()=>reject(new Error("synthetic timeout")),{once:true});
      setTimeout(()=>resolve(new Response("synthetic complete file")),100_000);
    })};
    const exportResult=edge.fetch(new Request("https://whisky.example/api/v1/library/export"),{WHISKY_WEB:binding});
    const ordinaryResult=edge.fetch(new Request("https://whisky.example/api/v1/me"),{WHISKY_WEB:binding});
    await vi.advanceTimersByTimeAsync(110_000);
    expect((await exportResult).status).toBe(200);
    expect((await ordinaryResult).status).toBe(503);
  } finally {vi.clearAllTimers();vi.restoreAllMocks();vi.useRealTimers();}
});
