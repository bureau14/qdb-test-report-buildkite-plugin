<!-- Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/components/details/ExecutionDetails.vue -->
<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import TestExecution from "../common/TestExecution.ts";
import DetailsHeader from "./DetailsHeader.vue";
import DetailsSections from "./DetailsSections.vue";
import ExecutionArtifacts from "./ExecutionArtifacts.vue";
import DurationLabel from "./DurationLabel.vue";
import TestResultStatusIcon from "../common/TestResultStatusIcon.vue";
import { testResultStatusBackgroundColorClasses } from "../common/TestResultStatus.ts";

const { t } = useI18n();
const props = defineProps<{ execution: TestExecution }>();

function formattedCount(key: string, count?: number): string[] {
  return count ? [t(key, { count: count }, count)] : [];
}

const summaryMessage = computed(() => {
  const summary = props.execution.summary;
  if (!summary) {
    const fallbackNodeCount = props.execution.size();
    return t(
      "executionSummary.testCount",
      { count: fallbackNodeCount },
      fallbackNodeCount,
    );
  }

  return [
    t(
      "executionSummary.testCount",
      { count: summary.logicalTests },
      summary.logicalTests,
    ),
    t(
      "executionSummary.targetCount",
      { count: summary.targets },
      summary.targets,
    ),
    ...formattedCount("executionSummary.errored", summary.statusCounts.ERRORED),
    ...formattedCount("executionSummary.failed", summary.statusCounts.FAILED),
    ...formattedCount("executionSummary.aborted", summary.statusCounts.ABORTED),
    ...formattedCount("executionSummary.skipped", summary.statusCounts.SKIPPED),
    ...(summary.ctestExecutions
      ? [`${summary.ctestExecutions} CTest executions`]
      : []),
    ...(summary.ctestStatusCounts?.FAILED
      ? [`${summary.ctestStatusCounts.FAILED} failed CTest executions`]
      : []),
    ...(summary.ctestStatusCounts?.ERRORED
      ? [`${summary.ctestStatusCounts.ERRORED} errored CTest executions`]
      : []),
  ].join(", ");
});
</script>

<template>
  <DetailsHeader :title="execution.name">
    <template #below>
      <div class="mt-3 flex flex-wrap gap-2">
        <div
          class="inline-flex mb-2 border-2 rounded-full px-2 py-1 text-white"
          :class="
            testResultStatusBackgroundColorClasses(execution.overallStatus())
          "
        >
          <TestResultStatusIcon
            :status="execution.overallStatus()"
            color="text-white"
          />
          <span
            class="ml-1 tracking-wide text-sm text-white font-bold self-center"
          >
            {{ summaryMessage }}
          </span>
        </div>
        <DurationLabel
          :millis="execution.durationMillis"
          :label="
            execution.summary?.durationKind === 'summed-case-time'
              ? 'Summed case time'
              : undefined
          "
        />
      </div>
    </template>
  </DetailsHeader>
  <DetailsSections :sections="execution.sections" />
  <details
    v-if="execution.artifacts.length"
    class="mx-4 border-t border-neutral-200 dark:border-neutral-700"
  >
    <summary class="cursor-pointer py-3 text-sm">
      Build artifacts · {{ execution.artifacts.length }} files
    </summary>
    <ExecutionArtifacts
      :artifacts="execution.artifacts"
      title="Build artifacts"
    />
  </details>
</template>
