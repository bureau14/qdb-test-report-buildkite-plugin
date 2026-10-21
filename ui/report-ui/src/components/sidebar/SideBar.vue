<!-- Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/components/sidebar/SideBar.vue -->
<script setup lang="ts">
import {inject, onBeforeUnmount, onMounted, watch} from "vue";
import {ResizableConfig, vResizable} from "vue-resizables";

import Selection from "../common/Selection.ts";
import TestExecution from "../common/TestExecution.ts";

import ExecutionTree from "./ExecutionTree.vue";
import ToolBar from "./ToolBar.vue";
import {treeStateKey} from "./TreeState.ts";

const selection = defineModel<Selection|undefined>("selection");
const props = defineProps<{executions : TestExecution[]}>();

const treeState = inject(treeStateKey)!;

function nodeIdFromHash(hash: string): string|undefined {
  if (!hash.startsWith("#node=")) {
    return undefined;
  }
  try {
    return decodeURIComponent(hash.slice("#node=".length));
  } catch {
    return undefined;
  }
}

function selectionFromLocationHash(): Selection|undefined {
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
  edge : {
    right : true,
  },
  size : {
    min : {
      width : 192, // min-w-48
    },
  },
};
</script>

<template>
  <div
    v-resizable="resizeConfig"
    class="report-sidebar-inner"
  >
    <ToolBar :executions="executions" />
    <ExecutionTree
      v-model:selection="selection"
      :executions="executions"
    />
  </div>
</template>
