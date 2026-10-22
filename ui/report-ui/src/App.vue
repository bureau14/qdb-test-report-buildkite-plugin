<!-- Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/App.vue -->
<script setup lang="ts">
import TestExecution from "./components/common/TestExecution.ts";
import ReportPresentation from "./components/ReportPresentation.vue";

defineProps<{executions : TestExecution[]}>();
</script>

<template>
  <ReportPresentation :executions="executions" />
</template>
