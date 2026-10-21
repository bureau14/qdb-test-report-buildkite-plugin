<script setup lang="ts">
import TestExecution from "../common/TestExecution.ts";

import DarkModeSwitch from "./DarkModeSwitch.vue";
import ExecutionSummary from "./ExecutionSummary.vue";

defineProps<{executions : TestExecution[]}>();
</script>
<template>
  <header class="report-topbar">
    <ExecutionSummary :executions="executions" />
    <DarkModeSwitch />
  </header>
</template>
