<!-- Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/App.vue -->
<script setup lang="ts">
import {computed, provide, reactive, ref, watch} from "vue";

import Selection from "./components/common/Selection.ts";
import TestExecution from "./components/common/TestExecution.ts";
import ExecutionDetails from "./components/details/ExecutionDetails.vue";
import FailureNavigation from "./components/details/FailureNavigation.vue";
import TestNodeDetails from "./components/details/TestNodeDetails.vue";
import StatusBar from "./components/header/StatusBar.vue";
import SideBar from "./components/sidebar/SideBar.vue";
import TreeState, {treeStateKey} from "./components/sidebar/TreeState.ts";

const props = defineProps<{executions : TestExecution[]}>();
const selection = ref<Selection|undefined>();
performance.mark("report-tree-state-create-start");
const treeState = reactive(new TreeState(props.executions));
performance.mark("report-tree-state-create-end");
performance.measure(
  "report-tree-state-create",
  "report-tree-state-create-start",
  "report-tree-state-create-end",
);
provide(treeStateKey, treeState);
const problems = computed(
  () => props.executions.flatMap((execution) => execution.problems().map(
                                   (node) => new Selection(execution, node))));
watch(selection, (next) => {
  if (!next)
    return;
  if (!(next.item instanceof TestExecution) &&
      !treeState.isVisible(next.execution.nodeStatuses(next.item)))
    treeState.clearFilters();
  if (treeState.hasActiveSearch() &&
      (next.item instanceof TestExecution ||
        ![next.item, ...next.execution.parents(next.item)].some(
          (node) => treeState.matchesSearch(node.name)))) {
    treeState.searchQuery = "";
  }
  treeState.revealNode(next.execution, next.item, false);
});
performance.mark("report-initial-selection-start");
selection.value = TestExecution.initialSelection(props.executions);
performance.mark("report-initial-selection-end");
performance.measure(
  "report-initial-selection",
  "report-initial-selection-start",
  "report-initial-selection-end",
);
</script>

<template>
  <main
    class="report-app"
  >
    <StatusBar :executions="executions" />
    <div class="report-workspace">
      <SideBar
        v-model:selection="selection"
        :executions="executions"
        class="report-sidebar"
      />
      <div class="report-details">
        <FailureNavigation v-model:selection="selection" :problems="problems" />
        <ExecutionDetails
          v-if="selection?.item instanceof TestExecution"
          v-model:selection="selection"
          :execution="selection?.item"
        />
        <TestNodeDetails
          v-else-if="selection"
          v-model:selection="selection"
          :execution="selection?.execution"
          :node="selection?.item as TestNodeData"
        />
      </div>
    </div>
  </main>
</template>
