import Selection from "./Selection.ts";
import TestExecution from "./TestExecution.ts";

export interface ReportResult {
  key: string;
  selection: Selection;
  name: string;
  path: string;
  reason: string;
  status: string;
  source: SourceData|undefined;
  ctest: boolean;
  search: string;
}

export interface ResultGroup {
  key: string;
  name: string;
  reason: string;
  status: string;
  results: ReportResult[];
}

export type ResultScope = "problems"|"tests"|"ctest";

export interface ResultFilter {
  scope: ResultScope;
  search: string;
  suite: string;
  status: string;
}

export function isProblem(status: string): boolean {
  return status === "FAILED" || status === "ERRORED";
}

export function collectResults(executions: TestExecution[]): ReportResult[] {
  return executions.flatMap(
      (execution) => execution.executionNodes().map((node) => {
        const source = execution.sourceData(node);
        const suffix = source ? " - " + source.target : "";
        const name = suffix && node.name.endsWith(suffix)
                         ? node.name.slice(0, -suffix.length)
                         : node.name;
        const path =
            execution.parents(node).map((parent) => parent.name).join(" / ");
        const reason = execution.reason(node);
        return {
          key : JSON.stringify([ execution.id, node.id ]),
          selection : new Selection(execution, node),
          name,
          path,
          reason,
          status : node.status,
          source,
          ctest : source?.suite.toLowerCase() === "ctest" ||
                      execution.parents(node).some(
                          (parent) => parent.name.toLowerCase() === "ctest"),
          search : [
            name, path, reason, source?.suite, source?.target
          ].join(" ").toLocaleLowerCase(),
        };
      }));
}

export function filterResults(results: ReportResult[],
                              filter: ResultFilter): ReportResult[] {
  const search = filter.search.trim().toLocaleLowerCase();
  return results.filter(
      (result) => (filter.scope === "ctest" ? result.ctest : !result.ctest) &&
                  (filter.scope !== "problems" || isProblem(result.status)) &&
                  (!filter.status || result.status === filter.status) &&
                  (!filter.suite || result.source?.suite === filter.suite) &&
                  (!search || result.search.includes(search)));
}

export function groupResults(results: ReportResult[],
                             grouped: boolean): ResultGroup[] {
  const groups = new Map<string, ResultGroup>();
  for (const result of results) {
    const key =
        grouped ? JSON.stringify([ result.name, result.status, result.reason ])
                : result.key;
    let group = groups.get(key);
    if (!group) {
      group = {
        key,
        name : result.name,
        status : result.status,
        reason : result.reason,
        results : []
      };
      groups.set(key, group);
    }
    group.results.push(result);
  }
  return [...groups.values() ];
}

export function countOutcomes(executions: TestExecution[],
                              ctest: boolean): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const execution of executions) {
    const summary = execution.summary;
    const values = ctest
                       ? summary?.ctestStatusCounts
                       : summary?.logicalStatusCounts || summary?.statusCounts;
    if (values) {
      for (const [status, count] of Object.entries(values))
        counts[status] = (counts[status] || 0) + count;
    } else {
      for (const result of collectResults([
             execution
           ]).filter((result) => result.ctest === ctest)) {
        counts[result.status] = (counts[result.status] || 0) + 1;
      }
    }
  }
  return counts;
}

export function valueMismatch(reason: string):
    {row: string; expected : string; actual : string}|undefined {
  const match =
      reason.match(/mismatched row (\d+): expected '([^']*)', got '([^']*)'/);
  return match ? {row : match[1], expected : match[2], actual : match[3]}
               : undefined;
}

export function reportIdentity(execution: TestExecution):
    Record<string, string> {
  const result: Record<string, string> = {};
  for (const section of execution.sections.filter(
           (section) => section.title === "Report summary")) {
    for (const block of section.blocks.filter((block) =>
                                                  block.type === "kvp")) {
      Object.assign(result, block.content as Record<string, string>);
    }
  }
  return result;
}

export function safeReportUrl(value: string|undefined): string|undefined {
  try {
    const url = new URL((value || "").replace(/^link:/, ""));
    return [ "https:", "http:" ].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}

export function relatedResults(result: ReportResult,
                               results: ReportResult[]): ReportResult[] {
  const artifacts = result.selection.execution.sourceArtifactsForNode(
      result.selection.item as TestNodeData);
  const ids = new Set(
      artifacts.map((artifact) => artifact.executionId).filter(Boolean));
  if (!ids.size)
    return [];
  return results.filter(
      (candidate) =>
          candidate.ctest !== result.ctest &&
          (candidate.ctest || isProblem(candidate.status)) &&
          candidate.selection.execution
              .sourceArtifactsForNode(candidate.selection.item as TestNodeData)
              .some((artifact) =>
                        artifact.executionId && ids.has(artifact.executionId)));
}
