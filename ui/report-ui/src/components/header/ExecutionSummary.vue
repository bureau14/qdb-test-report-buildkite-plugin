/**
 * Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/components/header/ExecutionSummary.vue
 */
<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import TestResultStatusIcon from "../common/TestResultStatusIcon.vue";
import TestExecution from "../common/TestExecution.ts";

const { t } = useI18n();
const { executions } = defineProps<{ executions: TestExecution[] }>();
const overallStatus = computed(() => TestExecution.overallStatus(executions));

function formattedCount(key: string, count?: number): string[] {
  return count ? [t(key, { count: count }, count)] : [];
}

function summaryCount(field: keyof ExecutionSummaryData): number | undefined {
  const summaries = executions.map((e) => e.summary);
  if (summaries.some((summary) => !summary)) {
    return undefined;
  }
  return summaries.reduce(
    (sum, summary) => sum + (summary?.[field] as number),
    0,
  );
}

function statusCount(status: string): number | undefined {
  const summaries = executions.map((e) => e.summary);
  if (summaries.some((summary) => !summary)) {
    return TestExecution.statusCount(executions).get(status);
  }
  return summaries.reduce(
    (sum, summary) => sum + (summary?.statusCounts[status] || 0),
    0,
  );
}

const summaryMessage = computed(() => {
  const logicalTestCount = summaryCount("logicalTests");
  const targetCount = summaryCount("targets");
  const fallbackNodeCount = executions
    .map((e) => e.size())
    .reduce((sum, current) => sum + current, 0);

  return [
    logicalTestCount !== undefined
      ? t(
          "executionSummary.testCount",
          { count: logicalTestCount },
          logicalTestCount,
        )
      : t(
          "executionSummary.testCount",
          { count: fallbackNodeCount },
          fallbackNodeCount,
        ),
    ...(targetCount !== undefined
      ? [t("executionSummary.targetCount", { count: targetCount }, targetCount)]
      : []),
    ...formattedCount("executionSummary.errored", statusCount("ERRORED")),
    ...formattedCount("executionSummary.failed", statusCount("FAILED")),
    ...formattedCount("executionSummary.aborted", statusCount("ABORTED")),
    ...formattedCount("executionSummary.skipped", statusCount("SKIPPED")),
  ].join(", ");
});
</script>

<template>
  <div class="p-px px-1 inline-flex">
    <TestResultStatusIcon :status="overallStatus" color="text-white" />
    <span class="ml-1 mt-px font-bold self-center">{{ summaryMessage }}</span>
    <span
      v-if="executions.length > 1"
      class="ml-1 mt-px font-bold self-center text-white/60 dark:text-white/50"
    >
      ({{
        $t(
          "executionSummary.execution",
          { count: executions.length },
          executions.length,
        )
      }})
    </span>
  </div>
</template>
