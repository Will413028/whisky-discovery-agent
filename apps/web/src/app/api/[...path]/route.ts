import { proxy } from "../../../features/identity/proxy";
import { planProxy } from "../../../features/discovery/proxy";
import { researchReadProxy } from "../../../features/research/proxy";
import {controlProxy, isControlPath} from "../../../features/control/proxy";
import { apiUpstream } from "../../../shared/api/upstream.server";
import {catalogProxy} from "../../../features/catalog/proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function forward(request: Request) {
  const pathname = new URL(request.url).pathname;
  const adapter = pathname === "/api/v1/catalog" || pathname.startsWith("/api/v1/catalog/") ? catalogProxy
    : isControlPath(pathname) ? controlProxy
    : pathname === "/api/v1/plans" || pathname.startsWith("/api/v1/plans/") ? planProxy
    : pathname === "/api/v1/tasks" || pathname.startsWith("/api/v1/tasks/") || pathname.startsWith("/api/v1/commands/") || pathname.startsWith("/api/v1/reports/") ? researchReadProxy : proxy;
  return adapter(request, apiUpstream(process.env.WHISKY_API_ORIGIN));
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
export const HEAD = forward;
export const OPTIONS = forward;
