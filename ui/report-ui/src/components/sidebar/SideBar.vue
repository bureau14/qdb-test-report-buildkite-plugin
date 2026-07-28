<!-- Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/components/sidebar/SideBar.vue -->
<script setup lang="ts">
import { ResizableConfig, vResizable } from "vue-resizables";
import ExecutionTree from "./ExecutionTree.vue";
import ToolBar from "./ToolBar.vue";
import TestExecution from "../common/TestExecution.ts";
import Selection from "../common/Selection.ts";
import { onBeforeUnmount, onMounted, provide, reactive, watch } from "vue";
import TreeState, { treeStateKey } from "./TreeState.ts";

const selection = defineModel<Selection | undefined>("selection");
const props = defineProps<{ executions: TestExecution[] }>();

performance.mark("report-tree-state-create-start");
const treeState = reactive(new TreeState(props.executions));
performance.mark("report-tree-state-create-end");
performance.measure(
  "report-tree-state-create",
  "report-tree-state-create-start",
  "report-tree-state-create-end",
);
provide(treeStateKey, treeState);

function nodeIdFromHash(hash: string): string | undefined {
  if (!hash.startsWith("#node=")) {
    return undefined;
  }
  try {
    return decodeURIComponent(hash.slice("#node=".length));
  } catch {
    return undefined;
  }
}

function selectionFromLocationHash(): Selection | undefined {
  const nodeId = nodeIdFromHash(window.location.hash);
  if (!nodeId) {
    return undefined;
  }
  for (const execution of props.executions) {
    const node = execution.node(nodeId);
    if (node) {
      return new Selection(execution, node);
    }
  }
  return undefined;
}

function selectLocationHash() {
  const linkedSelection = selectionFromLocationHash();
  if (!linkedSelection) {
    return;
  }
  treeState.revealNode(linkedSelection.execution, linkedSelection.item);
  selection.value = linkedSelection;
}

watch(selection, (next) => {
  if (!next) {
    return;
  }
  const locator = `#node=${encodeURIComponent(next.item.id)}`;
  if (window.location.hash !== locator) {
    window.history.replaceState(null, "", locator);
  }
});

onMounted(() => {
  selectLocationHash();
  window.addEventListener("hashchange", selectLocationHash);
});

onBeforeUnmount(() => {
  window.removeEventListener("hashchange", selectLocationHash);
});

const resizeConfig: ResizableConfig = {
  edge: {
    right: true,
  },
  size: {
    min: {
      width: 192, // min-w-48
    },
  },
};
</script>

<template>
  <div
    v-resizable="resizeConfig"
    class="resize-x bg-neutral-100 dark:bg-neutral-800 min-w-48 text-sm"
  >
    <ToolBar :executions="executions" class="sticky top-0 left-0" />
    <ExecutionTree
      v-model:selection="selection"
      :executions="executions"
      class="ml-1.5 mt-2.5"
    />
  </div>
</template>
