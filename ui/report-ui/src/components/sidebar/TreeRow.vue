<!-- Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/components/sidebar/TreeRow.vue -->
<script setup lang="ts">
/* global TestNodeData */
import {ChevronDown, ChevronRight} from "@lucide/vue";
import {computed, inject} from "vue";

import {defaultIconProps} from "../common/icon.ts";
import {formatCount, formatDuration} from "../common/presentation.ts";
import Selection from "../common/Selection.ts";
import TestExecution from "../common/TestExecution.ts";
import TestResultStatusIcon from "../common/TestResultStatusIcon.vue";

import {treeStateKey} from "./TreeState.ts";
import type {VisibleTreeRow} from "./VisibleTree.ts";

const treeState = inject(treeStateKey)!;
const selection = defineModel<Selection|undefined>("selection");
const props = defineProps<{row : VisibleTreeRow}>();
const isRoot = computed(() => props.row.node instanceof TestExecution);
const counts =
  computed(() => props.row.execution.counts(
             isRoot.value ? undefined : props.row.node as TestNodeData));
const status = computed(() => isRoot.value ? props.row.execution.overallStatus()
                                           : props.row.execution.displayStatus(
                                               props.row.node as TestNodeData));
const name = computed(() => isRoot.value ? props.row.node.name
                                         : props.row.execution.displayName(
                                             props.row.node as TestNodeData));
const reason = computed(
  () => !isRoot.value &&
            props.row.execution.isLogicalTest(props.row.node as TestNodeData)
          ? props.row.execution.problemReason(props.row.node as TestNodeData)
          : "");
const selected =
  computed(() => selection.value?.execution.id === props.row.execution.id &&
                 selection.value?.item.id === props.row.node.id);
function select() {
  selection.value = new Selection(props.row.execution, props.row.node);
}
</script>
<template>
  <div class="test-tree-row" :class="{ 'is-selected': selected }" :style="{ paddingLeft: row.depth * 14 + 'px' }">
    <button v-if="row.hasChildren" type="button" class="tree-disclosure" :aria-label="(treeState.nodes[row.node.id]?.collapsed ? 'Expand ' : 'Collapse ') + row.node.name" :aria-expanded="!treeState.nodes[row.node.id]?.collapsed" @click="treeState.toggleNode(row.node.id)"><ChevronRight v-if="treeState.nodes[row.node.id]?.collapsed" v-bind="defaultIconProps" /><ChevronDown v-else v-bind="defaultIconProps" /></button>
    <span v-else class="tree-disclosure-spacer" />
    <button type="button" class="tree-node-select" :aria-current="selected ? 'true' : undefined" :title="row.node.name + (reason ? ' — ' + reason : '')" @click="select">
      <TestResultStatusIcon :status="status" />
      <span class="tree-node-name">{{ name }}</span>
      <span v-if="reason" class="tree-node-reason">{{ reason }}</span>
    </button>
    <span class="tree-counts">
      <span v-if="counts.FAILED" class="tree-count" data-status="FAILED" :title="counts.FAILED + ' failed executions'">{{ formatCount(counts.FAILED) }}F</span>
      <span v-if="counts.ERRORED" class="tree-count" data-status="ERRORED" :title="counts.ERRORED + ' errored executions'">{{ formatCount(counts.ERRORED) }}E</span>
      <span v-if="counts.SKIPPED && !counts.FAILED && !counts.ERRORED" class="tree-count" data-status="SKIPPED">{{ formatCount(counts.SKIPPED) }} skip</span>
      <span v-else-if="!counts.FAILED && !counts.ERRORED && row.hasChildren" class="report-muted">{{ formatCount(counts.SUCCESSFUL || 0) }}</span>
    </span>
    <span class="tree-duration">{{ formatDuration(row.node.durationMillis) }}</span>
  </div>
</template>
