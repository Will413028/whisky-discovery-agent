import {readinessProbe} from "../../../shared/api/readiness";
import {apiUpstream} from "../../../shared/api/upstream.server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function GET() {
  return readinessProbe(apiUpstream(process.env.WHISKY_API_ORIGIN));
}
