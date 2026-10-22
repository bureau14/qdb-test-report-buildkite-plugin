<!-- Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/components/details/ExecutionDetails.vue -->
<script setup lang="ts">
import Selection from "../common/Selection.ts";
import TestExecution from "../common/TestExecution.ts";

import BranchOverview from "./BranchOverview.vue";
import DetailsHeader from "./DetailsHeader.vue";
import DetailsSections from "./DetailsSections.vue";
import ExecutionArtifacts from "./ExecutionArtifacts.vue";

const selection = defineModel<Selection|undefined>("selection");
defineProps<{execution : TestExecution}>();
</script>
<template>
  <DetailsHeader :title="execution.name" />
  <BranchOverview v-model:selection="selection" :execution="execution" />
  <DetailsSections v-if="execution.sections.some((section) => !['Tags', 'Report summary'].includes(section.title))" :sections="execution.sections.filter((section) => !['Tags', 'Report summary'].includes(section.title))" />
  <details class="metadata-section"><summary>Source and provenance</summary><DetailsSections :sections="execution.sections.filter((section) => ['Tags', 'Report summary'].includes(section.title))" /></details>
  <details v-if="execution.artifacts.length" class="metadata-section"><summary>Build artifacts · {{ execution.artifacts.length }} files</summary><ExecutionArtifacts :artifacts="execution.artifacts" title="Build artifacts" /></details>
</template>
