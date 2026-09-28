import { env } from "cloudflare:workers";
import { observationProxy, type ObservationUpstream } from "../../../features/research/proxy";

export function POST(request: Request) {
  const binding = (env as unknown as { WHISKY_API?: ObservationUpstream }).WHISKY_API;
  return observationProxy(request, binding);
}
