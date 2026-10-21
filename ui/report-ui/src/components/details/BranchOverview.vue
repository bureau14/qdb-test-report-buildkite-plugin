<script setup lang="ts">
/* global TestNodeData */
import {computed} from "vue";

import {
  formatCount,
  formatDuration,
  statusLabel
} from "../common/presentation.ts";
import Selection from "../common/Selection.ts";
import TestExecution from "../common/TestExecution.ts";
import TestResultStatusIcon from "../common/TestResultStatusIcon.vue";

const selection = defineModel<Selection|undefined>("selection");
const props = defineProps<{execution : TestExecution; node?: TestNodeData}>();
const counts =
  computed(() => !props.node && props.execution.summary?.logicalStatusCounts ||
                 props.execution.counts(props.node));
const outcomes = [ "SUCCESSFUL", "FAILED", "ERRORED", "SKIPPED", "ABORTED" ];
const children =
  computed(() => props.node ? props.execution.children(props.node)
                            : props.execution.roots());
const comparison =
  computed(() => !!props.node && props.execution.isLogicalTest(props.node));
const affected = computed(() => children.value.filter((node) => {
  const values = props.execution.counts(node);
  return (values.FAILED || 0) + (values.ERRORED || 0) > 0;
}));
const rows =
  computed(() => comparison.value || !affected.value.length ? children.value
                                                            : affected.value);
const summary = computed(() => props.execution.summary);
function select(node: TestNodeData) {
  selection.value = new Selection(props.execution, node);
}
</script>
<template>
  <section class="branch-overview" aria-label="Selection overview">
    <p class="report-muted overview-caption">{{ !node && summary?.logicalStatusCounts ? 'Logical test outcomes' : 'Platform execution outcomes' }} · counts include all statuses</p>
    <div class="outcome-counts">
      <div v-for="status in outcomes.filter((status) => status !== 'ABORTED' || counts[status])" :key="status" :data-status="status"><strong>{{ formatCount(counts[status] || 0) }}</strong><span>{{ statusLabel(status) }}</span></div>
    </div>
    <template v-if="!node && summary">
      <h3>Execution scope</h3>
      <dl class="scope-list">
        <div><dt>Logical tests</dt><dd>{{ formatCount(summary.logicalTests) }}</dd></div>
        <div><dt>Platform executions</dt><dd>{{ formatCount(summary.platformExecutions) }}</dd></div>
        <div><dt>Targets</dt><dd>{{ summary.resolvedPlatforms?.join(', ') || formatCount(summary.targets) }}</dd></div>
        <div v-if="summary.ctestExecutions !== undefined"><dt>CTest checks</dt><dd>{{ formatCount(summary.ctestExecutions) }} total · {{ summary.ctestStatusCounts?.FAILED || 0 }} failed · {{ summary.ctestStatusCounts?.ERRORED || 0 }} errored</dd></div>
        <div><dt>{{ summary.durationKind === 'summed-case-time' ? 'Summed case time' : 'Duration' }}</dt><dd>{{ formatDuration(execution.durationMillis) }}</dd></div>
      </dl>
    </template>
    <h3 v-if="rows.length">{{ comparison ? 'Platform comparison' : affected.length ? 'Affected branches' : 'Test branches' }}</h3>
    <div v-if="rows.length" class="report-table-wrapper">
      <table class="report-table">
        <thead><tr><th>{{ comparison ? 'Platform' : 'Suite / test' }}</th><th>{{ comparison ? 'Status / reason' : 'Problems' }}</th><th class="number-cell">{{ comparison ? 'Duration' : 'Summed case time' }}</th></tr></thead>
        <tbody><tr v-for="child in rows" :key="child.id">
          <td><button type="button" class="report-text-button branch-link" @click="select(child)">{{ comparison ? execution.displayName(child) : child.name }}</button></td>
          <td v-if="comparison"><span class="comparison-status"><TestResultStatusIcon :status="child.status" />{{ statusLabel(child.status) }}</span><p class="report-muted">{{ execution.reason(child) || '—' }}</p></td>
          <td v-else><span class="failed-count">{{ execution.counts(child).FAILED || 0 }} failed</span> · {{ execution.counts(child).ERRORED || 0 }} errored</td>
          <td class="number-cell">{{ formatDuration(child.durationMillis) }}</td>
        </tr></tbody>
      </table>
    </div>
  </section>
</template>
