import { researchStreamProxy } from "../../../features/research/proxy";
import { apiUpstream } from "../../../shared/api/upstream.server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function POST(request: Request) {
  return researchStreamProxy(request, apiUpstream(process.env.WHISKY_API_ORIGIN));
}
