import TestExecution from "./TestExecution.ts";

export function formatCount(value: number): string {
  return value.toLocaleString("en-US");
}

export function formatDuration(millis: number): string {
  if (!Number.isFinite(millis))
    return "—";
  if (millis >= 60000)
    return `${Math.floor(millis / 60000)}m ${
      Math.floor((millis % 60000) / 1000)}s`;
  if (millis >= 1000)
    return `${(millis / 1000).toFixed(2)}s`;
  return `${Math.max(0, Math.round(millis))}ms`;
}

export function statusLabel(status: string): string {
  return ({
    SUCCESSFUL : "Passed",
    FAILED : "Failed",
    ERRORED : "Errored",
    SKIPPED : "Skipped",
    ABORTED : "Aborted"
  } as Record<string, string>)[status] ||
         status;
}

export function summaryCount(executions: TestExecution[], field: "logicalTests"|
  "targets"|"platformExecutions"|"ctestExecutions"): number|undefined {
  if (executions.some((execution) => execution.summary?.[field] === undefined))
    return undefined;
  return executions.reduce(
    (sum, execution) => sum + (execution.summary?.[field] || 0), 0);
}

export function statusCounts(
  executions: TestExecution[]): Record<string, number> {
  const result: Record<string, number> = {};
  for (const execution of executions) {
    for (const [status, count] of Object.entries(execution.counts())) {
      result[status] = (result[status] || 0) + count;
    }
  }
  return result;
}
