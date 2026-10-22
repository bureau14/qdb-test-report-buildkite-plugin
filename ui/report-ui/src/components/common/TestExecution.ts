/**
 * Modified from original source:
 * https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/components/common/TestExecution.ts
 */
import Selection from "./Selection.ts";

export default class TestExecution {
  private static readonly STATUSES = [
    "SKIPPED",
    "ABORTED",
    "SUCCESSFUL",
    "FAILED",
    "ERRORED",
  ];

  static initialSelection(executions: TestExecution[]): Selection|undefined {
    if (executions.length > 0) {
      return new Selection(executions[0], executions[0]);
    }
    return undefined;
  }

  private static isFailedOrErrored(status: string) {
    return status === "FAILED" || status == "ERRORED";
  }

  static overallStatus(executions: TestExecution[]): string {
    let maxStatusIndex = 0;
    executions.forEach((e) => {
      maxStatusIndex = Math.max(
          maxStatusIndex,
          TestExecution.STATUSES.indexOf(e.overallStatus()),
      );
    });
    return TestExecution.STATUSES[maxStatusIndex];
  }

  static statusCount(executions: TestExecution[]): Map<string, number> {
    const statusCount = new Map<string, number>();
    TestExecution.STATUSES.forEach((s) => statusCount.set(s, 0));
    executions.forEach((e) => {
      e.statusCount().forEach((count, status) => {
        statusCount.set(status, statusCount.get(status)! + count);
      });
    });
    return statusCount;
  }

  public readonly id: string;
  public readonly name: string;
  public readonly durationMillis: number;
  public readonly sections: SectionData[];
  public readonly summary: ExecutionSummaryData|undefined;
  public readonly artifacts: SourceArtifactData[];

  private readonly rootIds: string[];
  private readonly rootNodes: TestNodeData[];
  private readonly childrenMetadata: Map<string, ChildMetadata>;
  private readonly parentIds: Map<string, string>;
  private readonly parentDepths: Map<string, number>;
  private readonly testNodes: Map<string, TestNodeData>;
  private readonly nodesWithChildrenValue: TestNodeData[];
  private readonly overallStatusValue: string;
  private readonly statusCounts: Map<string, number>;
  private readonly subtreeCounts = new Map<string, Record<string, number>>();
  private readonly problemNodesValue: TestNodeData[];
  private readonly sourceTables: SourceTables|undefined;
  private readonly sourceArtifactTable: SourceArtifactData[]|undefined;
  private readonly tagTables: TagTables|undefined;

  constructor(execution: ExecutionData) {
    this.id = execution.id;
    this.name = execution.name;
    this.durationMillis = execution.durationMillis;
    this.sections = execution.sections || [];
    this.summary = execution.summary;
    this.artifacts = execution.artifacts || [];
    this.sourceTables = execution.sourceTables;
    this.sourceArtifactTable = execution.sourceArtifactTable;
    this.tagTables = execution.tagTables;
    this.rootIds = execution.roots || [];
    this.childrenMetadata = new Map(
        Object.entries(execution.children ? execution.children : []),
    );
    this.parentIds = new Map<string, string>();
    this.childrenMetadata.forEach(
        (children,
         p) => { children.ids?.forEach((c) => this.parentIds.set(c, p)); });
    this.testNodes = new Map(execution.testNodes?.map((n) => [n.id, n]));
    this.rootNodes = this.rootIds.map((id) => this.testNodes.get(id)!);
    this.nodesWithChildrenValue = Array.from(this.childrenMetadata.keys())
                                      .map(
                                          (id) => this.testNodes.get(id)!,
                                      );
    this.parentDepths = new Map<string, number>();
    this.statusCounts = new Map<string, number>();
    TestExecution.STATUSES.forEach((s) => this.statusCounts.set(s, 0));

    // Input/archive errors have no testcase leaf; retain their report-level
    // status.
    let maxStatusIndex = Math.max(
        0,
        TestExecution.STATUSES.indexOf(this.summary?.rootStatus ?? ""),
    );
    const problems: TestNodeData[] = [];
    for (const node of this.testNodes.values()) {
      const statusIndex = TestExecution.STATUSES.indexOf(node.status);
      maxStatusIndex = Math.max(maxStatusIndex, statusIndex);
      this.statusCounts.set(
          node.status,
          this.statusCounts.get(node.status)! + 1,
      );
      if (TestExecution.isFailedOrErrored(node.status)) {
        problems.push(node);
      }
    }
    this.overallStatusValue = TestExecution.STATUSES[maxStatusIndex];
    this.problemNodesValue = problems;
    const collectCounts = (node: TestNodeData): Record<string, number> => {
      const counts: Record<string, number> = {};
      const children = this.children(node);
      if (!children.length && node.status)
        counts[node.status] = 1;
      for (const child of children) {
        for (const [status, count] of Object.entries(collectCounts(child))) {
          counts[status] = (counts[status] || 0) + count;
        }
      }
      this.subtreeCounts.set(node.id, counts);
      return counts;
    };
    this.rootNodes.forEach(collectCounts);
  }

  executionNodes(): TestNodeData[] {
    return [...this.testNodes.values() ].filter((node) => !!node.status);
  }

  problems(): TestNodeData[] { return this.problemNodesValue; }

  counts(node?: TestNodeData): Record<string, number> {
    if (node)
      return this.subtreeCounts.get(node.id) || {};
    if (!this.summary)
      return Object.fromEntries(this.statusCounts);
    const counts = {...this.summary.statusCounts};
    for (const [status, count] of Object.entries(
             this.summary.ctestStatusCounts || {})) {
      counts[status] = (counts[status] || 0) + count;
    }
    return counts;
  }

  displayStatus(node: TestNodeData): string {
    const statuses = this.nodeStatuses(node);
    return [...TestExecution.STATUSES ].reverse().find(
               (s) => statuses.includes(s)) ||
           "SKIPPED";
  }

  isLogicalTest(node: TestNodeData): boolean {
    return node.tags?.[0] === 1 ||
           (this.children(node).length > 0 &&
            this.children(node).every((child) => !!child.status));
  }

  displayName(node: TestNodeData): string {
    const source = this.sourceData(node);
    return source && node.name.endsWith(` - ${source.target}`) ? source.target
                                                               : node.name;
  }

  reason(node: TestNodeData): string {
    const section = node.sections?.find((s) => s.title === "Reason");
    return section?.blocks.filter((b) => typeof b.content === "string")
               .map((b) => String(b.content))
               .join(" ") ||
           "";
  }

  problemReason(node: TestNodeData): string {
    if (node.status)
      return this.reason(node);
    return this.children(node)
               .filter((child) => TestExecution.isFailedOrErrored(child.status))
               .map((child) => this.reason(child))
               .find(Boolean) ||
           "";
  }

  matchingExecutionCount(predicate: (node: TestNodeData) => boolean): number {
    return [...this.testNodes.values() ]
        .filter((node) => !!node.status && predicate(node))
        .length;
  }

  size(): number { return this.testNodes.size; }

  node(id: string): TestNodeData|TestExecution|undefined {
    return id === this.id ? this : this.testNodes.get(id);
  }

  nodesWithChildren(): TestNodeData[] { return this.nodesWithChildrenValue; }

  roots(): TestNodeData[] { return this.rootNodes; }

  children(node: TestNodeData): TestNodeData[] {
    if (this.childrenMetadata.has(node.id)) {
      return this.childrenMetadata.get(node.id)!.ids!.map(
          (id) => this.testNodes.get(id)!);
    }
    return [];
  }

  parents(node: TestNodeData): (TestNodeData|TestExecution)[] {
    if (this.parentIds.has(node.id)) {
      const parentId = this.parentIds.get(node.id)!;
      const parent = this.testNodes.get(parentId)!;
      return [...this.parents(parent), parent ];
    }
    return [ this ];
  }

  parentDepth(node: TestNodeData): number {
    if (this.parentDepths.has(node.id)) {
      return this.parentDepths.get(node.id)!;
    }
    const parentId = this.parentIds.get(node.id);
    if (!parentId) {
      this.parentDepths.set(node.id, 1);
      return 1;
    }
    const parent = this.testNodes.get(parentId)!;
    const depth = this.parentDepth(parent) + 1;
    this.parentDepths.set(node.id, depth);
    return depth;
  }

  nodeStatuses(node: TestNodeData): string[] {
    if (this.childrenMetadata.has(node.id)) {
      return this.childrenMetadata.get(node.id)!.childStatuses!;
    }
    return node.status ? [ node.status ] : [];
  }

  overallStatus(): string { return this.overallStatusValue; }

  statusCount(): Map<string, number> { return this.statusCounts; }

  sourceData(node: TestNodeData): SourceData|undefined {
    if (!node.source || !this.sourceTables) {
      return undefined;
    }
    return {
      target : this.sourceTables.targets[node.source[0]],
      suite : this.sourceTables.suites[node.source[1]],
      xml : this.sourceTables.xmls[node.source[2]],
      jobUrl : node.source.length > 3 && node.source[3] >= 0
                   ? this.sourceTables.jobUrls[node.source[3]]
                   : undefined,
      jobId : node.source.length > 4 && node.source[4] >= 0
                  ? this.sourceTables.jobIds[node.source[4]]
                  : undefined,
      buildUrl : node.source.length > 5 && node.source[5] >= 0
                     ? this.sourceTables.buildUrls[node.source[5]]
                     : undefined,
      xmlUrl : node.source.length > 6 && node.source[6] >= 0
                   ? this.sourceTables.xmlUrls[node.source[6]]
                   : undefined,
      qdbProcessId : node.source.length > 7 && node.source[7] >= 0
                         ? this.sourceTables.qdbProcessIds?.[node.source[7]]
                         : undefined,
    };
  }

  sourceDataForNode(node: TestNodeData): SourceData[] {
    const sources: SourceData[] = [];
    const sourceKeys = new Set<string>();

    const collect = (current: TestNodeData) => {
      const source = this.sourceData(current);
      if (source) {
        const key = [
          source.target,
          source.suite,
          source.xml,
          source.jobId,
          source.xmlUrl,
          source.qdbProcessId,
        ].join("\u0000");
        if (!sourceKeys.has(key)) {
          sourceKeys.add(key);
          sources.push(source);
        }
      }
      this.children(current).forEach(collect);
    };

    collect(node);
    return sources;
  }

  sourceArtifactsForNode(node: TestNodeData): SourceArtifactData[] {
    const artifacts: SourceArtifactData[] = [];
    const artifactKeys = new Set<string>();

    const collect = (current: TestNodeData) => {
      for (const artifactIndex of current.sourceArtifacts || []) {
        const artifact = this.sourceArtifactTable?.[artifactIndex];
        if (!artifact) {
          continue;
        }
        const key = [ artifact.name, artifact.relativePath, artifact.key ].join(
            "\u0000",
        );
        if (!artifactKeys.has(key)) {
          artifactKeys.add(key);
          artifacts.push(artifact);
        }
      }
      this.children(current).forEach(collect);
    };

    collect(node);
    return artifacts;
  }

  tagLabels(node: TestNodeData): string[]|undefined {
    if (!node.tags || !this.tagTables) {
      return undefined;
    }
    if (node.tags[0] === 0) {
      return [ `testsuite:${this.tagTables.suites[node.tags[1] as number]}` ];
    }

    const classname = this.tagTables.classnames[node.tags[2] as number];
    const testName = this.tagTables.testNames[node.tags[3] as number];
    const logicalId = this.tagTables.logicalIds[node.tags[4] as number];
    const failedPlatforms = node.tags[5] as number[];
    const erroredPlatforms = node.tags[6] as number[];
    const skippedPlatforms = node.tags[7] as number[];
    return [
      `logical-test-id:${logicalId}`,
      `testsuite:${this.tagTables.suites[node.tags[1] as number]}`,
      `classname:${classname}`,
      `test-name:${testName}`,
      ...failedPlatforms.map(
          (index) => `failed-platform:${this.tagTables!.platforms[index]}`,
          ),
      ...erroredPlatforms.map(
          (index) => `errored-platform:${this.tagTables!.platforms[index]}`,
          ),
      ...skippedPlatforms.map(
          (index) => `skipped-platform:${this.tagTables!.platforms[index]}`,
          ),
    ].sort();
  }
}
