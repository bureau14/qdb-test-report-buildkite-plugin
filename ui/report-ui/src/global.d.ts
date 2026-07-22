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
    sourceTables: SourceTables | undefined;
    tagTables: TagTables | undefined;
    roots: string[];
    children: Record<string, ChildMetadata>;
    testNodes: TestNodeData[] | undefined;
  }

  interface TestNodeData extends Data {
    status: string;
    source: number[] | undefined;
    sourceArtifacts: SourceArtifactData[] | undefined;
    tags: TagData | undefined;
  }

  interface SourceArtifactData {
    name: string;
    relativePath: string;
    key: string;
    url: string | undefined;
    sizeBytes: number;
  }

  type TagData = Array<number | number[]>;

  interface SourceData {
    target: string;
    suite: string;
    xml: string;
    buildUrl: string | undefined;
    jobUrl: string | undefined;
    jobId: string | undefined;
    xmlUrl: string | undefined;
  }

  interface SourceTables {
    targets: string[];
    suites: string[];
    xmls: string[];
    buildUrls: string[];
    jobUrls: string[];
    jobIds: string[];
    xmlUrls: string[];
  }

  interface TagTables {
    suites: string[];
    platforms: string[];
    classnames: string[];
    testNames: string[];
    logicalIds: string[];
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
