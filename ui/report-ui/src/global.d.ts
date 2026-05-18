/**
 * Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/global.d.ts
 */
export declare global {
  interface Data {
    id: string;
    name: string;
    durationMillis: number;
    sections: SectionData[] | undefined;
  }

  interface ExecutionSummaryData {
    rawTestcases: number;
    suites: number;
    logicalTests: number;
    platformExecutions: number;
    targets: number;
    resolvedPlatforms: string[];
    structuralContainers: number;
    statusCounts: Record<string, number>;
    logicalStatusCounts: Record<string, number>;
    rootStatus: string;
  }

  interface ExecutionData extends Data {
    summary: ExecutionSummaryData | undefined;
    roots: string[];
    children: Record<string, ChildMetadata>;
    testNodes: TestNodeData[] | undefined;
  }

  interface TestNodeData extends Data {
    status: string;
  }

  interface ChildMetadata {
    ids: string[];
    childStatuses: string[];
  }

  interface SectionData {
    title: string;
    metaInfo: string;
    blocks: BlockData[];
  }

  interface BlockData {
    type: string;
    content: never;
  }

  interface ImageBlockData extends BlockData {
    altText: string;
  }

  interface VideoBlockData extends BlockData {
    mediaType: string;
  }

  declare namespace globalThis {
    var testExecutions: ExecutionData[]; // eslint-disable-line no-var
  }
}
