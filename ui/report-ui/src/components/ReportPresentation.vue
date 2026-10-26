<script setup lang="ts">
import {useClipboard} from "@vueuse/core";
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch
} from "vue";

import {
  formatCount,
  formatDuration,
  statusLabel
} from "./common/presentation.ts";
import {
  collectResults,
  countOutcomes,
  filterResults,
  groupResults,
  isProblem,
  relatedResults,
  reportIdentity,
  safeReportUrl,
  sortResultGroups
} from "./common/report-presentation.ts";
import type {
  ReportResult, ResultFilter, ResultGroup, ResultScope, ResultSort} from
  "./common/report-presentation.ts";
import Selection from "./common/Selection.ts";
import TestExecution from "./common/TestExecution.ts";
import TestResultStatusIcon from "./common/TestResultStatusIcon.vue";
import DetailsSections from "./details/DetailsSections.vue";
import ExecutionArtifacts from "./details/ExecutionArtifacts.vue";
import ExecutionDetails from "./details/ExecutionDetails.vue";
import FailureReason from "./details/FailureReason.vue";
import TestNodeDetails from "./details/TestNodeDetails.vue";
import DarkModeSwitch from "./header/DarkModeSwitch.vue";

const props = defineProps<{executions : TestExecution[]}>();
performance.mark("report-result-index-create-start");
const results = collectResults(props.executions);
performance.mark("report-result-index-create-end");
performance.measure("report-result-index-create",
                    "report-result-index-create-start",
                    "report-result-index-create-end");
performance.mark("report-initial-selection-start");
const selection = ref<Selection>();
const selectedGroup = ref<ResultGroup>();
performance.mark("report-initial-selection-end");
performance.measure("report-initial-selection",
                    "report-initial-selection-start",
                    "report-initial-selection-end");
const filter = reactive<ResultFilter>(
    {scope : "problems", search : "", suite : "", status : ""});
const grouped = ref(true);
const sortMode = ref<ResultSort>("problems");
const limit = ref(100);
const showDetails = ref(false);
const detailsPane = ref<HTMLElement>();
const workspace = ref<HTMLElement>();
const sidebarWidth = ref(380);
const logicalCounts = countOutcomes(props.executions, false);
const ctestCounts = countOutcomes(props.executions, true);
const testProblemCount =
    (logicalCounts.FAILED || 0) + (logicalCounts.ERRORED || 0);
const ctestProblemCount =
    (ctestCounts.FAILED || 0) + (ctestCounts.ERRORED || 0);
const ctestCount =
    Object.values(ctestCounts).reduce((sum, count) => sum + count, 0);
const groups =
    groupResults(
        results.filter((result) => !result.ctest && isProblem(result.status)),
        true)
        .sort((a, b) => b.results.length - a.results.length ||
                        a.name.localeCompare(b.name));
const filtered = computed(() => filterResults(results, filter));
const groupedView =
    computed(() => filter.scope === "problems" && grouped.value);
const rows = computed(
    () => sortResultGroups(groupResults(filtered.value, groupedView.value),
                           sortMode.value));
const suites = [
  ...new Set(results.filter((result) => !result.ctest)
                 .map((result) => result.source?.suite)
                 .filter((suite): suite is string => !!suite))
].sort();
const identities =
    props.executions.map((execution) => reportIdentity(execution));
const targets = [...new Set(props.executions.flatMap(
    (execution) => execution.summary?.resolvedPlatforms || [])) ];
const currentResult =
    computed(() => results.find((result) => result.selection.execution.id ===
                                                selection.value?.execution.id &&
                                            result.selection.item.id ===
                                                selection.value?.item.id));
const related = computed(
    () => currentResult.value ? relatedResults(currentResult.value, results)
                              : []);
const rowIndex = computed(
    () => rows.value.findIndex(
        (row) => selectedGroup.value
                     ? row.key === selectedGroup.value.key
                     : row.results.some((result) => result.key ===
                                                    currentResult.value?.key)));
const selectedKey = computed(
    () => rowIndex.value >= 0 ? rows.value[rowIndex.value].key : undefined);
const navigationNoun =
    computed(() => filter.scope === "ctest"      ? "CTest check"
                   : groupedView.value           ? "Problem group"
                   : filter.scope === "problems" ? "Test problem"
                                                 : "Test result");
const outcomes = computed(
    () => filter.scope === "problems"
              ? [ "FAILED", "ERRORED" ]
              : [ "FAILED", "ERRORED", "SUCCESSFUL", "SKIPPED", "ABORTED" ]);
const hasProblems =
    props.executions.some((execution) => isProblem(execution.overallStatus()));
const sumTime = props.executions.reduce(
    (sum, execution) => sum + execution.durationMillis, 0);
const {copy, copied, isSupported} = useClipboard();
function copyLink() { copy(window.location.href); }

function setScope(scope: ResultScope, status = "") {
  filter.scope = scope;
  filter.status = status;
  filter.suite = "";
  limit.value = 100;
  showDetails.value = false;
}
function resetFilters() {
  filter.search = "";
  filter.suite = "";
  filter.status = "";
}
function setHash(hash: string) {
  if (window.location.hash !== hash)
    window.history.pushState(
        null, "", window.location.pathname + window.location.search + hash);
}
function writeSelection() {
  if (!selection.value)
    return;
  const params = new URLSearchParams(
      {report : selection.value.execution.id, node : selection.value.item.id});
  setHash("#" + params.toString());
}
function openDetails() {
  showDetails.value = true;
  nextTick(() => {
    if (detailsPane.value)
      detailsPane.value.scrollTop = 0;
  });
}
function selectResult(result: ReportResult) {
  selectedGroup.value = undefined;
  selection.value = result.selection;
  writeSelection();
  openDetails();
}
function selectGroup(group: ResultGroup) {
  if (!groupedView.value || group.results.length === 1) {
    selectResult(group.results[0]);
    return;
  }
  selectedGroup.value = group;
  selection.value = undefined;
  const first = group.results[0];
  setHash("#" + new URLSearchParams({
                  report : first.selection.execution.id,
                  group : first.selection.item.id
                }).toString());
  openDetails();
}
function selectOverview() {
  selectedGroup.value = undefined;
  selection.value = undefined;
  setHash("");
  openDetails();
}
function navigate(direction: number) {
  const index = rowIndex.value < 0 ? (direction > 0 ? -1 : 0) : rowIndex.value;
  const row =
      rows.value[(index + direction + rows.value.length) % rows.value.length];
  if (row)
    selectGroup(row);
}
function restoreHash() {
  const params = new URLSearchParams(window.location.hash.slice(1));
  const id = params.get("node") || params.get("group");
  const report = params.get("report");
  const execution = props.executions.find(
      (execution) =>
          (!report || execution.id === report) && !!execution.node(id || ""));
  if (!execution || !id) {
    selectedGroup.value = undefined;
    selection.value = undefined;
    return;
  }
  const result =
      results.find((result) => result.selection.execution === execution &&
                               result.selection.item.id === id);
  if (params.has("group") && result) {
    const group = groups.find(
        (group) => group.results.some((item) => item.key === result.key));
    if (group && group.results.length > 1) {
      selectedGroup.value = group;
      selection.value = undefined;
      openDetails();
      return;
    }
  }
  selectedGroup.value = undefined;
  selection.value = new Selection(execution, execution.node(id)!);
  if (result) {
    filter.scope = result.ctest               ? "ctest"
                   : isProblem(result.status) ? "problems"
                                              : "tests";
    if (filter.scope === "problems")
      grouped.value = false;
  }
  openDetails();
}
function resizeSidebar(value: number) {
  sidebarWidth.value = Math.max(
      280, Math.min(650, (workspace.value?.clientWidth || 1000) - 360, value));
}
function startResize(event: PointerEvent) {
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
}
function resize(event: PointerEvent) {
  if ((event.currentTarget as HTMLElement).hasPointerCapture(event.pointerId))
    resizeSidebar(event.clientX -
                  (workspace.value?.getBoundingClientRect().left || 0));
}
watch(filter, () => { limit.value = 100; });
watch(groupedView, (active) => {
  if (!active && sortMode.value === "problems")
    sortMode.value = "status";
});
onMounted(() => {
  restoreHash();
  window.addEventListener("popstate", restoreHash);
  window.addEventListener("hashchange", restoreHash);
});
onBeforeUnmount(() => {
  window.removeEventListener("popstate", restoreHash);
  window.removeEventListener("hashchange", restoreHash);
});
</script>

<template>
  <main class="report-app presentation-app">
    <header class="report-topbar">
      <div class="report-heading">
        <p class="presentation-eyebrow">QUASAR / TEST RESULTS</p>
        <div class="report-heading-title"><h1>{{ executions.length === 1 ? executions[0].name : 'Full test report' }}</h1><span class="status-badge" :data-status="hasProblems ? 'FAILED' : 'SUCCESSFUL'">{{ hasProblems ? 'Completed with problems' : 'Completed successfully' }}</span></div>
        <div class="report-heading-meta">
          <template v-for="(identity, index) in identities" :key="index">
            <a v-if="safeReportUrl(identity['Buildkite build'])" :href="safeReportUrl(identity['Buildkite build'])" target="_blank" rel="noopener noreferrer">Build #{{ safeReportUrl(identity['Buildkite build'])?.split('/').pop() }} ↗</a>
            <a v-if="safeReportUrl(identity['Git commit'])" :href="safeReportUrl(identity['Git commit'])" target="_blank" rel="noopener noreferrer">{{ safeReportUrl(identity['Git commit'])?.split('/').pop()?.slice(0, 8) }} ↗</a>
            <span v-if="identity['Generated at']">Generated {{ identity['Generated at'].replace('T', ' ').replace('Z', ' UTC') }}</span>
          </template>
          <span>{{ targets.join(' · ') }}</span>
        </div>
      </div>
      <div class="presentation-actions"><button type="button" class="report-button" @click="selectOverview">Overview</button><DarkModeSwitch /></div>
    </header>
    <section class="presentation-summary" aria-label="Test results and separate CTest checks">
      <button type="button" class="summary-card" @click="setScope('problems')">
        <span class="summary-title">Tests with problems</span>
        <strong class="summary-value" :class="testProblemCount ? 'failed-count' : 'report-muted'">{{ formatCount(testProblemCount) }}</strong>
        <small class="summary-description">
          <span>{{ formatCount(logicalCounts.FAILED || 0) }} {{ logicalCounts.FAILED === 1 ? 'failed test' : 'failed tests' }}</span>
          <span>{{ formatCount(logicalCounts.ERRORED || 0) }} {{ logicalCounts.ERRORED === 1 ? 'test with an execution error' : 'tests with execution errors' }}</span>
        </small>
      </button>
      <button type="button" class="summary-card" @click="setScope('tests', 'SUCCESSFUL')">
        <span class="summary-title">Passed tests</span>
        <strong class="summary-value passed-count">{{ formatCount(logicalCounts.SUCCESSFUL || 0) }}</strong>
        <small class="summary-description">Tests reported as successful.</small>
      </button>
      <button type="button" class="summary-card" @click="setScope('tests', 'SKIPPED')">
        <span class="summary-title">Skipped tests</span>
        <strong class="summary-value skipped-count">{{ formatCount(logicalCounts.SKIPPED || 0) }}</strong>
        <small class="summary-description">Tests reported as skipped.<span>Select to view their reasons.</span></small>
      </button>
      <button type="button" class="summary-card" @click="setScope('ctest', 'PROBLEMS')">
        <span class="summary-title">CTest checks with problems</span>
        <strong class="summary-value" :class="ctestProblemCount ? 'failed-count' : 'report-muted'">{{ formatCount(ctestProblemCount) }}</strong>
        <small class="summary-description"><span>Out of {{ formatCount(ctestCount) }} CTest {{ ctestCount === 1 ? 'check' : 'checks' }}.</span><span>Counted separately from individual tests.</span></small>
      </button>
    </section>
    <div ref="workspace" class="presentation-workspace" :class="{'show-details': showDetails}" :style="{'--sidebar-width': sidebarWidth + 'px'}">
      <aside class="presentation-sidebar" aria-label="Results browser">
        <div class="presentation-controls">
          <nav class="presentation-tabs" aria-label="Result views"><button v-for="scope in (['problems', 'tests', 'ctest'] as const)" :key="scope" type="button" :aria-pressed="filter.scope === scope" @click="setScope(scope)">{{ scope === 'problems' ? 'Problems' : scope === 'tests' ? 'All tests' : 'CTest checks' }}</button></nav>
          <label class="sr-only" for="result-search">Search names, paths, or failure messages</label><input id="result-search" v-model="filter.search" class="report-search" type="search" placeholder="Search names, paths, or messages…">
          <label class="presentation-field" for="result-suite">Suite</label><select id="result-suite" v-model="filter.suite" class="report-search" :disabled="filter.scope === 'ctest'"><option value="">All suites</option><option v-for="suite in suites" :key="suite">{{ suite }}</option></select>
          <div class="presentation-filters" aria-label="Filter result statuses"><button v-if="filter.scope === 'ctest'" type="button" class="report-button" :aria-pressed="filter.status === 'PROBLEMS'" @click="filter.status = 'PROBLEMS'">With problems</button><button type="button" class="report-button" :aria-pressed="!filter.status" @click="filter.status = ''">All statuses</button><button v-for="status in outcomes" :key="status" type="button" class="report-button" :aria-pressed="filter.status === status" @click="filter.status = status">{{ statusLabel(status) }}</button></div>
          <div class="presentation-actions"><button type="button" class="report-text-button" @click="resetFilters">Reset filters</button><button v-if="filter.scope === 'problems'" type="button" class="report-text-button" :aria-pressed="grouped" @click="grouped = !grouped">Group matching failures: {{ grouped ? 'on' : 'off' }}</button></div>
        </div>
        <div class="presentation-list-caption"><span role="status" aria-live="polite">{{ groupedView ? rows.length + (rows.length === 1 ? ' group · ' : ' groups · ') : '' }}{{ formatCount(filtered.length) }} {{ filter.scope === 'ctest' ? (filtered.length === 1 ? 'check' : 'checks') : (filtered.length === 1 ? 'execution' : 'executions') }}</span><label class="sr-only" for="result-sort">Sort results</label><select id="result-sort" v-model="sortMode" class="presentation-sort"><option v-if="groupedView" value="problems">Problem count ↓</option><option value="status">Status · problems first</option><option value="name">Name A–Z</option><option value="duration">Duration ↓</option></select></div>
        <div class="presentation-results">
          <button v-for="row in rows.slice(0, limit)" :key="row.key" type="button" class="presentation-result" :aria-current="row.key === selectedKey" @click="selectGroup(row)"><span class="result-title">{{ row.name }}<span v-if="groupedView" class="result-count">{{ row.results.length }} {{ row.results.length === 1 ? 'result' : 'results' }}</span></span><span class="result-context"><TestResultStatusIcon :status="row.status" />{{ statusLabel(row.status) }} · {{ groupedView ? new Set(row.results.map((item) => item.source?.suite)).size + (new Set(row.results.map((item) => item.source?.suite)).size === 1 ? ' suite' : ' suites') : row.results[0].source?.suite }}</span><span v-if="row.reason" class="result-reason">{{ row.reason }}</span><span v-if="!groupedView && targets.length > 1" class="result-context">{{ row.results[0].source?.target }}</span></button>
          <p v-if="!rows.length" class="tree-empty-state">No results match these filters. Change the search or reset the filters.</p>
          <button v-if="rows.length > limit" type="button" class="report-button presentation-more" @click="limit += 100">Show next {{ Math.min(100, rows.length - limit) }} results</button>
        </div>
      </aside>
      <div class="presentation-divider" role="separator" tabindex="0" aria-label="Resize results browser" aria-orientation="vertical" aria-valuemin="280" aria-valuemax="650" :aria-valuenow="sidebarWidth" @pointerdown="startResize" @pointermove="resize" @keydown.left.prevent="resizeSidebar(sidebarWidth - 20)" @keydown.right.prevent="resizeSidebar(sidebarWidth + 20)" />
      <div ref="detailsPane" class="presentation-details">
        <nav class="presentation-detail-nav" aria-label="Scoped result navigation"><button type="button" class="report-button presentation-back" @click="showDetails = false">← Results</button><span>{{ rowIndex >= 0 ? navigationNoun + ' ' + (rowIndex + 1) + ' of ' + rows.length : selection || selectedGroup ? 'Selection outside current list' : 'Report overview' }}</span><button type="button" class="report-button" :disabled="!rows.length" @click="navigate(-1)">← Previous</button><button type="button" class="report-button" :disabled="!rows.length" @click="navigate(1)">Next →</button></nav>
        <template v-if="selectedGroup">
          <header class="details-heading"><p class="presentation-eyebrow">Matching failure group</p><h2>{{ selectedGroup.name }}</h2><div class="test-status-line"><span class="status-badge" :data-status="selectedGroup.status">{{ statusLabel(selectedGroup.status) }}</span><span>{{ selectedGroup.results.length }} affected executions</span><button v-if="isSupported" type="button" class="report-text-button" @click="copyLink">{{ copied ? 'Copied link' : 'Copy link' }}</button></div></header>
          <FailureReason :reason="selectedGroup.reason" :status="selectedGroup.status" />
          <section class="presentation-section"><h3>Affected executions</h3><div class="report-table-wrapper"><table class="report-table"><thead><tr><th>Suite / execution path</th><th>Platform</th><th class="number-cell">Case time</th></tr></thead><tbody><tr v-for="result in selectedGroup.results" :key="result.key"><td><button type="button" class="report-text-button" @click="selectResult(result)">{{ result.source?.suite || result.name }}</button><p class="presentation-path">{{ result.path }}</p></td><td>{{ result.source?.target }}</td><td class="number-cell">{{ formatDuration(result.selection.item.durationMillis) }}</td></tr></tbody></table></div><p class="presentation-hint">Grouped by test name, status, and exact message. Matching messages do not establish a shared cause.</p></section>
        </template>
        <template v-else-if="selection">
          <ExecutionDetails v-if="selection.item instanceof TestExecution" v-model:selection="selection" :execution="selection.item" />
          <TestNodeDetails v-else :key="selection.execution.id + ':' + selection.item.id" :selection="selection" :execution="selection.execution" :node="selection.item" @update:selection="selection = $event; writeSelection(); openDetails()">
            <template #related>
              <section v-if="related.length" class="presentation-related"><h3>{{ currentResult?.ctest ? 'Test problems in this execution' : 'Related CTest checks' }}</h3><p class="presentation-hint">Matched using execution artifact identity.</p><button v-for="result in related" :key="result.key" type="button" class="report-text-button" @click="selectResult(result)">{{ result.name }} · {{ statusLabel(result.status) }}</button></section>
            </template>
          </TestNodeDetails>
        </template>
        <template v-else>
          <header class="details-heading"><p class="presentation-eyebrow">Run overview</p><h2>{{ formatCount(testProblemCount) }} test {{ testProblemCount === 1 ? 'problem' : 'problems' }}, in {{ groups.length }} matching {{ groups.length === 1 ? 'group' : 'groups' }}</h2><p class="presentation-intro">Start with a failure pattern, then inspect its affected executions. CTest checks have their own view and are counted separately.</p></header>
          <DetailsSections v-for="execution in executions" :key="execution.id" :sections="execution.sections.filter((section) => !['Tags', 'Report summary'].includes(section.title))" />
          <section v-if="groups.length" class="presentation-section"><h3>Matching failure groups</h3><div class="report-table-wrapper"><table class="report-table"><thead><tr><th>Test / failure pattern</th><th>Status</th><th class="number-cell">Executions</th></tr></thead><tbody><tr v-for="group in groups" :key="group.key"><td><button type="button" class="report-text-button" @click="grouped = true; filter.scope = 'problems'; selectGroup(group)">{{ group.name }}</button><p class="presentation-hint">{{ group.reason }}</p></td><td>{{ statusLabel(group.status) }}</td><td class="number-cell">{{ group.results.length }}</td></tr></tbody></table></div><p class="presentation-hint">Headline outcomes count logical tests; groups and navigation retain individual platform executions.</p></section>
          <section class="presentation-section"><h3>Execution scope</h3><div class="presentation-scope"><div v-for="execution in executions" :key="execution.id"><strong>{{ formatCount(execution.summary?.logicalTests || 0) }}</strong><span>logical {{ execution.summary?.logicalTests === 1 ? 'test' : 'tests' }} · {{ execution.summary?.suites || 0 }} {{ execution.summary?.suites === 1 ? 'suite' : 'suites' }}</span><p>{{ formatCount(execution.summary?.platformExecutions || 0) }} platform {{ execution.summary?.platformExecutions === 1 ? 'execution' : 'executions' }}</p></div><div><strong>{{ formatDuration(sumTime) }}</strong><span>summed case time</span><p class="presentation-hint">Adds case durations; this is not elapsed build time.</p></div></div></section>
          <template v-for="execution in executions" :key="execution.id"><details v-if="execution.artifacts.length" class="metadata-section"><summary>Build artifacts · {{ execution.artifacts.length }} files</summary><ExecutionArtifacts :artifacts="execution.artifacts" title="Build artifacts" /></details><details class="metadata-section"><summary>Source and provenance · {{ execution.name }}</summary><DetailsSections :sections="execution.sections" /></details></template>
        </template>
      </div>
    </div>
  </main>
</template>
