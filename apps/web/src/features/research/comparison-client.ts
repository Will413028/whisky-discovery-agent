import type {components} from "../../../../../contracts/api";
import validComparison from "../../../../../contracts/comparison-report-view.validator.js";

export type ComparisonReportView = components["schemas"]["ComparisonReportViewV4"];

export async function readComparison(reportId: string, taskId: string, token: string, signal?: AbortSignal): Promise<ComparisonReportView | null> {
  const response = await fetch(`/api/v1/reports/${reportId}/comparison`, {
    headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal,
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(response.status === 401 ? "AUTH_REQUIRED" : "REQUEST_FAILED");
  const value:unknown = await response.json();
  if (!validComparison(value) || value.reportId !== reportId || value.taskId !== taskId) throw new Error("INVALID_RESPONSE");
  return value;
}
