// Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/components/sidebar/TreeState.ts
import TestExecution from "../common/TestExecution.ts";
import { InjectionKey } from "vue";

export const treeStateKey = Symbol() as InjectionKey<TreeState>;

const LARGE_TREE_NODE_THRESHOLD = 2000;

export default class TreeState {
  public readonly nodes: Record<string, NodeState>;

  public showAborted = false;
  public showFailedAndErrored = false;
  public showSkipped = false;
  public showSuccessful = false;
  public searchQuery = "";
  public sortMode: "alphabetical" | "execution" = "alphabetical";

  constructor(executions: TestExecution[]) {
    const nodes: Record<string, NodeState> = {};

    for (const execution of executions) {
      nodes[execution.id] = {
        collapsed: false,
      };

      const largeTree = execution.size() > LARGE_TREE_NODE_THRESHOLD;
      for (const node of execution.nodesWithChildren()) {
        const statuses = execution.nodeStatuses(node);
        const parentDepth = execution.parentDepth(node);
        const initiallyCollapsed = largeTree
          ? parentDepth > 0
          : parentDepth > 1 &&
            statuses.indexOf("FAILED") == -1 &&
            statuses.indexOf("ERRORED") == -1;

        nodes[node.id] = {
          collapsed: initiallyCollapsed,
        };
      }
    }

    this.nodes = nodes;
  }

  toggleShowAborted() {
    this.showAborted = !this.showAborted;
  }

  toggleShowFailedAndErrored() {
    this.showFailedAndErrored = !this.showFailedAndErrored;
  }

  toggleShowSuccessful() {
    this.showSuccessful = !this.showSuccessful;
  }

  toggleShowSkipped() {
    this.showSkipped = !this.showSkipped;
  }

  toggleSortMode() {
    this.sortMode =
      this.sortMode === "alphabetical" ? "execution" : "alphabetical";
  }

  collapseAll() {
    Object.keys(this.nodes).forEach((key) => {
      this.nodes[key].collapsed = true;
    });
  }

  expandAll() {
    Object.keys(this.nodes).forEach((key) => {
      this.nodes[key].collapsed = false;
    });
  }

  toggleNode(id: string) {
    this.nodes[id].collapsed = !this.nodes[id].collapsed;
  }

  clearFilters() {
    this.showAborted = false;
    this.showFailedAndErrored = false;
    this.showSkipped = false;
    this.showSuccessful = false;
    this.searchQuery = "";
  }

  revealNode(execution: TestExecution, node: TestNodeData | TestExecution) {
    this.clearFilters();
    if (!(node instanceof TestExecution)) {
      execution.parents(node).forEach((parent) => {
        const state = this.nodes[parent.id];
        if (state) {
          state.collapsed = false;
        }
      });
    }
    const state = this.nodes[node.id];
    if (state) {
      state.collapsed = false;
    }
  }

  hasActiveStatusFilter(): boolean {
    return (
      this.showAborted ||
      this.showFailedAndErrored ||
      this.showSkipped ||
      this.showSuccessful
    );
  }

  hasActiveSearch(): boolean {
    return this.searchQuery.trim().length > 0;
  }

  matchesSearch(name: string): boolean {
    const query = this.searchQuery.trim().toLocaleLowerCase();
    return query.length === 0 || name.toLocaleLowerCase().includes(query);
  }

  isVisible(statuses: string[]): boolean {
    if (!this.hasActiveStatusFilter()) {
      return true;
    }

    return (
      statuses.length == 0 ||
      statuses.filter((status) => {
        switch (status) {
          case "SUCCESSFUL":
            return this.showSuccessful;
          case "FAILED":
          case "ERRORED":
            return this.showFailedAndErrored;
          case "SKIPPED":
            return this.showSkipped;
          case "ABORTED":
            return this.showAborted;
        }
      }).length > 0
    );
  }
}

type NodeState = {
  collapsed: boolean;
};
