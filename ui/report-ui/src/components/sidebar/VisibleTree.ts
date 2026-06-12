// Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/components/sidebar/VisibleTree.ts
import TestExecution from "../common/TestExecution.ts";
import TreeState from "./TreeState.ts";

export type VisibleTreeRow = {
  id: string;
  execution: TestExecution;
  node: TestExecution | TestNodeData;
  depth: number;
  children: TestNodeData[];
  statuses: string[];
  hasChildren: boolean;
};

export function visibleRows(
  executions: TestExecution[],
  treeState: TreeState,
): VisibleTreeRow[] {
  const rows: VisibleTreeRow[] = [];

  function nodeStatuses(
    execution: TestExecution,
    node: TestExecution | TestNodeData,
  ): string[] {
    return node instanceof TestExecution ? [] : execution.nodeStatuses(node);
  }

  function visit(
    execution: TestExecution,
    node: TestExecution | TestNodeData,
    children: TestNodeData[],
    depth: number,
  ) {
    const statuses = nodeStatuses(execution, node);
    if (!treeState.isVisible(statuses)) {
      return;
    }

    rows.push({
      id: node.id,
      execution,
      node,
      depth,
      children,
      statuses,
      hasChildren: children.length > 0,
    });

    if (children.length > 0 && !treeState.nodes[node.id]?.collapsed) {
      for (const child of children) {
        visit(execution, child, execution.children(child), depth + 1);
      }
    }
  }

  for (const execution of executions) {
    visit(execution, execution, execution.roots(), 0);
  }

  return rows;
}
