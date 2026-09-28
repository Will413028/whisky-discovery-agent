import edge from "../../../edge/src/index";

export default {
  async fetch(request: Request, env: {ASSETS:{fetch(request:Request):Promise<Response>}}) {
    if (new URL(request.url).pathname === "/agent/observe") {
      return edge.fetch(request, {WHISKY_WEB:{fetch: (forwarded) => fetch(new Request("http://127.0.0.1:3421/agent/observe", forwarded))}});
    }
    return env.ASSETS.fetch(request);
  },
};
