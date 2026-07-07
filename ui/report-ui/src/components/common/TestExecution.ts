/**
 * Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/components/common/TestExecution.ts
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

  static initialSelection(executions: TestExecution[]): Selection | undefined {
    const failedExecution = executions.find((e) =>
      this.isFailedOrErrored(e.overallStatus()),
    );
    if (failedExecution) {
      const failedNode = failedExecution.firstFailedOrErroredNode;
      if (failedNode) {
        return new Selection(failedExecution, failedNode);
      }
    }
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
  public readonly summary: ExecutionSummaryData | undefined;

  private readonly rootIds: string[];
  private readonly rootNodes: TestNodeData[];
  private readonly childrenMetadata: Map<string, ChildMetadata>;
  private readonly parentIds: Map<string, string>;
  private readonly parentDepths: Map<string, number>;
  private readonly testNodes: Map<string, TestNodeData>;
  private readonly nodesWithChildrenValue: TestNodeData[];
  private readonly overallStatusValue: string;
  private readonly statusCounts: Map<string, number>;
  private readonly firstFailedOrErroredNode: TestNodeData | undefined;
  private readonly sourceTables: SourceTables | undefined;
  private readonly tagTables: TagTables | undefined;

  constructor(execution: ExecutionData) {
    this.id = execution.id;
    this.name = execution.name;
    this.durationMillis = execution.durationMillis;
    this.sections = execution.sections || [];
    this.summary = execution.summary;
    this.sourceTables = execution.sourceTables;
    this.tagTables = execution.tagTables;
    this.rootIds = execution.roots || [];
    this.childrenMetadata = new Map(
      Object.entries(execution.children ? execution.children : []),
    );
    this.parentIds = new Map<string, string>();
    this.childrenMetadata.forEach((children, p) => {
      children.ids?.forEach((c) => this.parentIds.set(c, p));
    });
    this.testNodes = new Map(execution.testNodes?.map((n) => [n.id, n]));
    this.rootNodes = this.rootIds.map((id) => this.testNodes.get(id)!);
    this.nodesWithChildrenValue = Array.from(this.childrenMetadata.keys()).map(
      (id) => this.testNodes.get(id)!,
    );
    this.parentDepths = new Map<string, number>();
    this.statusCounts = new Map<string, number>();
    TestExecution.STATUSES.forEach((s) => this.statusCounts.set(s, 0));

    let maxStatusIndex = 0;
    let firstFailedOrErroredNode: TestNodeData | undefined;
    for (const node of this.testNodes.values()) {
      const statusIndex = TestExecution.STATUSES.indexOf(node.status);
      maxStatusIndex = Math.max(maxStatusIndex, statusIndex);
      this.statusCounts.set(node.status, this.statusCounts.get(node.status)! + 1);
      if (!firstFailedOrErroredNode && TestExecution.isFailedOrErrored(node.status)) {
        firstFailedOrErroredNode = node;
      }
    }
    this.overallStatusValue = TestExecution.STATUSES[maxStatusIndex];
    this.firstFailedOrErroredNode = firstFailedOrErroredNode;
  }

  size(): number {
    return this.testNodes.size;
  }

  nodesWithChildren(): TestNodeData[] {
    return this.nodesWithChildrenValue;
  }

  roots(): TestNodeData[] {
    return this.rootNodes;
  }

  children(node: TestNodeData): TestNodeData[] {
    if (this.childrenMetadata.has(node.id)) {
      return this.childrenMetadata
        .get(node.id)!
        .ids!.map((id) => this.testNodes.get(id)!);
    }
    return [];
  }

  parents(node: TestNodeData): (TestNodeData | TestExecution)[] {
    if (this.parentIds.has(node.id)) {
      const parentId = this.parentIds.get(node.id)!;
      const parent = this.testNodes.get(parentId)!;
      return [...this.parents(parent), parent];
    }
    return [this];
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
    return node.status ? [node.status] : [];
  }

  overallStatus(): string {
    return this.overallStatusValue;
  }

  statusCount(): Map<string, number> {
    return this.statusCounts;
  }

  sourceData(node: TestNodeData): SourceData | undefined {
    if (!node.source || !this.sourceTables) {
      return undefined;
    }
    return {
      target: this.sourceTables.targets[node.source[0]],
      suite: this.sourceTables.suites[node.source[1]],
      xml: this.sourceTables.xmls[node.source[2]],
      jobUrl:
        node.source.length > 3 && node.source[3] >= 0
          ? this.sourceTables.jobUrls[node.source[3]]
          : undefined,
      jobId:
        node.source.length > 4 && node.source[4] >= 0
          ? this.sourceTables.jobIds[node.source[4]]
          : undefined,
      buildUrl:
        node.source.length > 5 && node.source[5] >= 0
          ? this.sourceTables.buildUrls[node.source[5]]
          : undefined,
    };
  }

  tagLabels(node: TestNodeData): string[] | undefined {
    if (!node.tags || !this.tagTables) {
      return undefined;
    }
    if (node.tags[0] === 0) {
      return [`testsuite:${this.tagTables.suites[node.tags[1] as number]}`];
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
      ...failedPlatforms.map((index) => `failed-platform:${this.tagTables!.platforms[index]}`),
      ...erroredPlatforms.map((index) => `errored-platform:${this.tagTables!.platforms[index]}`),
      ...skippedPlatforms.map((index) => `skipped-platform:${this.tagTables!.platforms[index]}`),
    ].sort();
  }
}
