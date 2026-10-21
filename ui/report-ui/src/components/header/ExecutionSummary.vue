<!-- Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/components/header/ExecutionSummary.vue -->
<script setup lang="ts">
import {computed} from "vue";

import {
  formatCount,
  statusLabel,
  summaryCount
} from "../common/presentation.ts";
import TestExecution from "../common/TestExecution.ts";
import TestResultStatusIcon from "../common/TestResultStatusIcon.vue";

const props = defineProps<{executions : TestExecution[]}>();
const status = computed(() => TestExecution.overallStatus(props.executions));
const tests = computed(() => summaryCount(props.executions, "logicalTests"));
const targets = computed(() => summaryCount(props.executions, "targets"));
const ctest = computed(() => summaryCount(props.executions, "ctestExecutions"));
</script>
<template>
  <div class="report-heading">
    <div class="report-heading-title">
      <span>{{ executions.length === 1 ? executions[0].name : "Full test report" }}</span>
      <span class="status-badge" :data-status="status"><TestResultStatusIcon :status="status" />{{ statusLabel(status) }}</span>
    </div>
    <div class="report-heading-meta">
      <span v-if="tests !== undefined">{{ formatCount(tests) }} logical tests</span>
      <span v-if="targets !== undefined">{{ formatCount(targets) }} targets</span>
      <span v-if="ctest !== undefined">{{ formatCount(ctest) }} CTest checks</span>
      <span v-if="executions.length > 1">{{ executions.length }} reports</span>
    </div>
  </div>
</template>
