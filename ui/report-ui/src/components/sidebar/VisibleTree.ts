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
  const searchMatches = new Set<string>();

  function sortedChildren<T extends { name: string }>(children: T[]): T[] {
    if (treeState.sortMode === "alphabetical") {
      return [...children].sort((left, right) =>
        left.name.localeCompare(right.name),
      );
    }
    return children;
  }

  function nodeStatuses(
    execution: TestExecution,
    node: TestExecution | TestNodeData,
  ): string[] {
    return node instanceof TestExecution ? [] : execution.nodeStatuses(node);
  }

  function addVisibleDescendants(
    execution: TestExecution,
    node: TestExecution | TestNodeData,
    children: TestNodeData[],
  ): boolean {
    const statuses = nodeStatuses(execution, node);
    let hasVisibleChild = false;
    for (const child of sortedChildren(children)) {
      hasVisibleChild =
        addVisibleDescendants(execution, child, execution.children(child)) ||
        hasVisibleChild;
    }
    if (treeState.isVisible(statuses) || hasVisibleChild) {
      searchMatches.add(node.id);
      return true;
    }
    return false;
  }

  function containsSearchMatch(
    execution: TestExecution,
    node: TestExecution | TestNodeData,
    children: TestNodeData[],
  ): boolean {
    const statuses = nodeStatuses(execution, node);
    const directMatch =
      treeState.matchesSearch(node.name) && treeState.isVisible(statuses);
    if (directMatch) {
      addVisibleDescendants(execution, node, children);
      return true;
    }
    let descendantMatch = false;
    for (const child of sortedChildren(children)) {
      descendantMatch =
        containsSearchMatch(execution, child, execution.children(child)) ||
        descendantMatch;
    }
    if (directMatch || descendantMatch) {
      searchMatches.add(node.id);
      return true;
    }
    return false;
  }

  if (treeState.hasActiveSearch()) {
    for (const execution of sortedChildren(executions)) {
      containsSearchMatch(execution, execution, execution.roots());
    }
  }

  function visit(
    execution: TestExecution,
    node: TestExecution | TestNodeData,
    children: TestNodeData[],
    depth: number,
  ) {
    const statuses = nodeStatuses(execution, node);
    const isSearchMatch =
      !treeState.hasActiveSearch() || searchMatches.has(node.id);
    if (!isSearchMatch || (!treeState.hasActiveSearch() && !treeState.isVisible(statuses))) {
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

    const hasMatchingChild = children.some((child) => searchMatches.has(child.id));
    const isExpanded =
      !treeState.nodes[node.id]?.collapsed ||
      (treeState.hasActiveSearch() && hasMatchingChild);
    if (children.length > 0 && isExpanded) {
      for (const child of sortedChildren(children)) {
        visit(execution, child, execution.children(child), depth + 1);
      }
    }
  }

  for (const execution of sortedChildren(executions)) {
    visit(execution, execution, execution.roots(), 0);
  }

  return rows;
}
