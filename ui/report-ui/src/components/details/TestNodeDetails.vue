<!-- Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/components/details/TestNodeDetails.vue -->
<script setup lang="ts">
import {Check, ChevronRight, Copy} from "@lucide/vue";
import {useClipboard} from "@vueuse/core";
import {computed} from "vue";

import {defaultIconProps} from "../common/icon.ts";
import {statusLabel} from "../common/presentation.ts";
import Selection from "../common/Selection.ts";
import TestExecution from "../common/TestExecution.ts";
import TestResultStatusIcon from "../common/TestResultStatusIcon.vue";

import {archiveMember} from "./archive-download.ts";
import ArchiveDownload from "./ArchiveDownload.vue";
import BranchOverview from "./BranchOverview.vue";
import DetailsHeader from "./DetailsHeader.vue";
import DetailsSections from "./DetailsSections.vue";
import DurationLabel from "./DurationLabel.vue";
import ExecutionArtifacts from "./ExecutionArtifacts.vue";
import FailureReason from "./FailureReason.vue";

/* global TestNodeData, SectionData */

const selection = defineModel<Selection|undefined>("selection");
const props = defineProps<{node : TestNodeData; execution : TestExecution}>();

function selectNode(node: TestNodeData|TestExecution) {
  selection.value = new Selection(props.execution, node);
}

const diagnostics =
    computed(() => (props.node.sections ||
                    []).filter((section) => section.title !== "Reason"));
const reason = computed(() => props.execution.reason(props.node));
const status = computed(() => props.execution.displayStatus(props.node));
const hasChildren =
    computed(() => props.execution.children(props.node).length > 0);
const source = computed(() => props.execution.sourceData(props.node));
const title = computed(
    () => source.value && props.node.name.endsWith(" - " + source.value.target)
              ? props.node.name.slice(0, -(source.value.target.length + 3))
              : props.node.name);
const locator = computed(() => window.location.href.split("#")[0] + "#" +
                               new URLSearchParams({
                                 report : props.execution.id,
                                 node : props.node.id
                               }).toString());
const {copy, copied, isSupported} = useClipboard({source : locator});
const artifacts = computed(
    () => props.execution.sourceArtifactsForNode(props.node),
);
const artifactSources = computed(
    () => props.execution.sourceDataForNode(props.node),
);

const parents = computed(() => props.execution.parents(props.node));
const sections = computed(() => {
  const result: SectionData[] = [];
  const tagLabels = props.execution.tagLabels(props.node);
  if (tagLabels) {
    result.unshift({
      title : "Tags",
      blocks : [ {type : "labels", content : tagLabels} ],
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
      const label = `JUnit XML ${index + 1} (${source.target} / ${
          source.suite} / ${source.xml})`;
      sourceContent[label] =
          source.xmlUrl ? `link:${source.xmlUrl}` : source.xml;
      if (source.qdbProcessId) {
        sourceContent[`QDB PID ${index + 1} (${source.xml})`] =
            source.qdbProcessId;
      }
    });
  }

  const synthesizedSections: SectionData[] = [
    {
      title : "Source",
      blocks : [ {type : "kvp", content : sourceContent} ],
    } as SectionData,
  ];

  return [...synthesizedSections, ...result ];
});
</script>


<template>
  <DetailsHeader :title="title">
    <template #above>
      <nav class="test-breadcrumbs" aria-label="Test path">
        <template v-for="parent in parents" :key="parent.id"><button type="button" class="report-text-button" @click="selectNode(parent)">{{ parent.name }}</button><ChevronRight v-bind="defaultIconProps" /></template>
      </nav>
    </template>
    <template #below>
      <div class="test-status-line"><span class="status-badge" :data-status="status"><TestResultStatusIcon :status="status" />{{ statusLabel(status) }}</span><span v-if="source" class="report-muted">{{ source.target }}</span><DurationLabel :millis="node.durationMillis" /></div>
      <div class="test-source-actions">
        <a v-if="source?.jobUrl" class="report-text-button" :href="source.jobUrl" target="_blank" rel="noopener noreferrer">Buildkite job ↗</a>
        <template v-if="source?.xmlUrl"><ArchiveDownload v-if="archiveMember(source.xmlUrl)" :reference="archiveMember(source.xmlUrl)!" label="JUnit XML" compact /><a v-else class="report-text-button" :href="source.xmlUrl" target="_blank" rel="noopener noreferrer">JUnit XML ↗</a></template>
        <button v-if="isSupported" type="button" class="report-button" @click="copy(locator)"><Check v-if="copied" v-bind="defaultIconProps" /><Copy v-else v-bind="defaultIconProps" />{{ copied ? 'Copied link' : 'Copy link' }}</button>
      </div>
    </template>
  </DetailsHeader>
  <FailureReason :reason="reason" :status="status" />
  <BranchOverview v-if="hasChildren" v-model:selection="selection" :execution="execution" :node="node" />
  <DetailsSections v-if="diagnostics.length" :sections="diagnostics" />
  <ExecutionArtifacts :artifacts="artifacts" :sources="artifactSources" />
  <details class="metadata-section"><summary>Source and provenance</summary><DetailsSections :sections="sections" /></details>
</template>
