<!-- Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/components/sidebar/TreeRow.vue -->
<script setup lang="ts">
import { computed, inject } from "vue";
import { ChevronDown, ChevronRight } from "@lucide/vue";
import Selection from "../common/Selection.ts";
import TestExecution from "../common/TestExecution.ts";
import ExecutionIcon from "../common/ExecutionIcon.vue";
import { defaultIconProps } from "../common/icon.ts";
import TestResultStatusIcon from "../common/TestResultStatusIcon.vue";
import { treeStateKey } from "./TreeState.ts";
import type { VisibleTreeRow } from "./VisibleTree.ts";

const treeState = inject(treeStateKey)!;
const selection = defineModel<Selection | undefined>("selection");
const props = defineProps<{
  row: VisibleTreeRow;
}>();

const nodeName = computed(() => props.row.node.name);
const isExecutionRoot = computed(() => props.row.node instanceof TestExecution);
const isSelected = computed(
  () =>
    selection.value?.item !== undefined &&
    selection.value.item.id === props.row.node.id,
);

function aggregateDisplayStatus(statuses: string[]): string | undefined {
  if (statuses.includes("ERRORED")) {
    return "ERRORED";
  }
  if (statuses.includes("FAILED")) {
    return "FAILED";
  }
  if (statuses.includes("SUCCESSFUL")) {
    return "SUCCESSFUL";
  }
  if (statuses.includes("SKIPPED")) {
    return "SKIPPED";
  }
  return undefined;
}

const rowStatus = computed(() => {
  if (isExecutionRoot.value) {
    return undefined;
  }
  if ("status" in props.row.node && props.row.node.status) {
    return props.row.node.status;
  }
  return aggregateDisplayStatus(props.row.statuses);
});
const paddingLeft = computed(() => `${props.row.depth * 0.75}rem`);

function toggleNode() {
  if (props.row.hasChildren) {
    treeState.toggleNode(props.row.node.id);
  }
}

function selectAndExpandNode() {
  selection.value = new Selection(props.row.execution, props.row.node);
  const record = treeState.nodes[props.row.node.id];
  if (record) {
    record.collapsed = false;
  }
}

if (defaultIconProps.size != 16) {
  throw new Error("Adjust ml-[16px] CSS class below!");
}
</script>

<template>
  <div
    class="flex h-6 items-center"
    :style="{ paddingLeft }"
  >
    <div
      v-if="row.hasChildren"
      class="cursor-pointer self-center shrink-0"
      @click="toggleNode()"
    >
      <ChevronRight
        v-if="treeState.nodes[row.node.id]?.collapsed"
        v-bind="defaultIconProps"
      />
      <ChevronDown v-else v-bind="defaultIconProps" />
    </div>
    <div
      class="cursor-pointer rounded-sm p-px px-1 inline-flex"
      :class="{
        'bg-neutral-300 dark:bg-neutral-600 font-bold': isSelected,
        'hover:bg-neutral-200 dark:hover:bg-neutral-700': !isSelected,
        'ml-[16px]': !row.hasChildren,
      }"
      role="link"
      :aria-label="nodeName"
      @click="selectAndExpandNode()"
    >
      <ExecutionIcon v-if="isExecutionRoot" />
      <TestResultStatusIcon v-else-if="rowStatus" :status="rowStatus" />
      <span class="ml-1 whitespace-nowrap">{{ nodeName }}</span>
    </div>
  </div>
</template>
