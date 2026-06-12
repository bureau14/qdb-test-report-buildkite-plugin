<!-- Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/components/sidebar/SideBar.vue -->
<script setup lang="ts">
import { ResizableConfig, vResizable } from "vue-resizables";
import ExecutionTree from "./ExecutionTree.vue";
import ToolBar from "./ToolBar.vue";
import TestExecution from "../common/TestExecution.ts";
import Selection from "../common/Selection.ts";
import { provide, reactive } from "vue";
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
