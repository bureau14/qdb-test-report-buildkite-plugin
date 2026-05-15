// Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/components/sidebar/TreeState.ts
import TestExecution from "../common/TestExecution.ts";
import { InjectionKey } from "vue";

export const treeStateKey = Symbol() as InjectionKey<TreeState>;

const LARGE_TREE_NODE_THRESHOLD = 2000;

export default class TreeState {
  public readonly nodes: Record<string, NodeState>;

  public showAborted = true;
  public showFailedAndErrored = true;
  public showSkipped = true;
  public showSuccessful = true;

  constructor(executions: TestExecution[]) {
    const nodes: Record<string, NodeState> = {};

    for (const execution of executions) {
      nodes[execution.id] = {
        collapsed: false,
      };

      const largeTree = execution.size() > LARGE_TREE_NODE_THRESHOLD;
      for (const node of execution.nodesWithChildren()) {
        const statuses = execution.nodeStatuses(node);
        const parentDepth = execution.parents(node).length;
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

  isVisible(statuses: string[]): boolean {
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
