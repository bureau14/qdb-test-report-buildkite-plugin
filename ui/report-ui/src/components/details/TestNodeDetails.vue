<!-- Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/components/details/TestNodeDetails.vue -->
<script setup lang="ts">
import { computed } from "vue";
import TestResultStatusIcon from "../common/TestResultStatusIcon.vue";
import { ChevronRight } from "@lucide/vue";
import TestExecution from "../common/TestExecution.ts";
import { testResultStatusBackgroundColorClasses } from "../common/TestResultStatus.ts";
import DurationLabel from "./DurationLabel.vue";
import DetailsSections from "./DetailsSections.vue";
import DetailsHeader from "./DetailsHeader.vue";
import Selection from "../common/Selection.ts";
import ExecutionIcon from "../common/ExecutionIcon.vue";
import { defaultIconProps } from "../common/icon.ts";
/* global TestNodeData */

const selection = defineModel<Selection | undefined>("selection");
const props = defineProps<{ node: TestNodeData; execution: TestExecution }>();

function selectNode(node: TestNodeData | TestExecution) {
  selection.value = new Selection(props.execution, node);
}

const parents = computed(() => props.execution.parents(props.node));
const sections = computed(() => {
  const result = props.node.sections ? [...props.node.sections] : [];
  const tagLabels = props.execution.tagLabels(props.node);
  if (tagLabels) {
    result.unshift({
      title: "Tags",
      blocks: [{ type: "labels", content: tagLabels }],
    } as SectionData);
  }

  const sources = props.execution.sourceDataForNode(props.node);
  if (sources.length === 0) {
    return result;
  }

  const sourceContent: Record<string, string> = {};
  if (sources.length === 1) {
    const source = sources[0];
    sourceContent.Target = source.target;
    sourceContent["Test suite"] = source.suite;
    sourceContent["JUnit XML"] = source.xmlUrl ? `link:${source.xmlUrl}` : source.xml;
    if (source.buildUrl) {
      sourceContent["Buildkite build"] = `link:${source.buildUrl}`;
    }
    if (source.jobUrl) {
      sourceContent["Buildkite job"] = `link:${source.jobUrl}`;
    }
    if (source.jobId) {
      sourceContent["Job ID"] = source.jobId;
    }
    if (source.qdbProcessId) {
      sourceContent["QDB PID"] = source.qdbProcessId;
    }
  } else {
    sources.forEach((source, index) => {
      const label = `JUnit XML ${index + 1} (${source.target} / ${source.suite} / ${source.xml})`;
      sourceContent[label] = source.xmlUrl ? `link:${source.xmlUrl}` : source.xml;
      if (source.qdbProcessId) {
        sourceContent[`QDB PID ${index + 1} (${source.xml})`] = source.qdbProcessId;
      }
    });
  }

  const synthesizedSections: SectionData[] = [
    {
      title: "Source",
      blocks: [{ type: "kvp", content: sourceContent }],
    } as SectionData,
  ];
  const sourceArtifacts = props.execution.sourceArtifactsForNode(props.node);
  if (sourceArtifacts.length > 0) {
    const artifactContent: Record<string, string> = {};
    const duplicateArtifactNames = sourceArtifacts.reduce(
      (counts, artifact) => {
        counts[artifact.name] = (counts[artifact.name] || 0) + 1;
        return counts;
      },
      {} as Record<string, number>,
    );
    for (const artifact of sourceArtifacts) {
      const label =
        duplicateArtifactNames[artifact.name] > 1
          ? `${artifact.name} / ${artifact.relativePath}`
          : artifact.name;
      artifactContent[label] = artifact.url
        ? `link:${artifact.url}\n${artifact.relativePath}`
        : artifact.key;
    }
    synthesizedSections.push({
      title: "Artifacts",
      blocks: [{ type: "kvp", content: artifactContent }],
    } as SectionData);
  }

  return [...synthesizedSections, ...result];
});
</script>

<template>
  <DetailsHeader :title="node.name">
    <template #above>
      <ul class="text-sm mb-3 inline-flex h-5">
        <li v-for="parent in parents" :key="parent.id" class="inline-flex">
          <ExecutionIcon
            v-if="parent instanceof TestExecution"
            class="-ml-px cursor-pointer"
            @click="selectNode(parent)"
          />
          <span
            v-else
            class="underline underline-offset-4 decoration-neutral-300 dark:decoration-neutral-700 hover:decoration-neutral-400 decoration-2 whitespace-nowrap cursor-pointer"
            @click="selectNode(parent)"
          >
            {{ parent.name }}
          </span>
          <ChevronRight
            v-bind="defaultIconProps"
            class="inline self-center mx-1 text-neutral-500"
          />
        </li>
      </ul>
    </template>
    <template #below>
      <div class="mt-3">
        <div
          class="inline-flex mb-2 border-2 rounded-full px-2 py-1 mr-2"
          :class="testResultStatusBackgroundColorClasses(node.status)"
        >
          <TestResultStatusIcon :status="node.status" color="text-white" />
          <span
            class="ml-1 tracking-wide text-sm text-white font-bold self-center"
            role="status"
            :aria-label="node.status"
            >{{ node.status }}</span
          >
        </div>
        <DurationLabel :millis="node.durationMillis" />
      </div>
    </template>
  </DetailsHeader>
  <DetailsSections :sections="sections" />
</template>
