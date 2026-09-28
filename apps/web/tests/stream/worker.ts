import { observationProxy } from "../../src/features/research/proxy";

export default {
  async fetch(request: Request, env: {ASSETS:{fetch(request:Request):Promise<Response>}}) {
    if (new URL(request.url).pathname === "/agent/observe") {
      return observationProxy(request, {fetch: (forwarded) => fetch(new Request("http://127.0.0.1:8419/agent/observe", forwarded))});
    }
    return env.ASSETS.fetch(request);
  },
};
