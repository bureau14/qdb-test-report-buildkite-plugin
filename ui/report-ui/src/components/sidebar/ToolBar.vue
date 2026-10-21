<!-- Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/components/sidebar/ToolBar.vue -->
<script setup lang="ts">
import {ArrowDownAZ, ChevronsDownUp, ChevronsUpDown} from "@lucide/vue";
import {computed, inject} from "vue";

import {defaultIconProps} from "../common/icon.ts";
import {formatCount, statusCounts} from "../common/presentation.ts";
import TestExecution from "../common/TestExecution.ts";

import {treeStateKey} from "./TreeState.ts";

const props = defineProps<{executions : TestExecution[]}>();
const treeState = inject(treeStateKey)!;
const counts = computed(() => statusCounts(props.executions));
const matching = computed(
  () => props.executions.reduce(
    (total, execution) =>
      total +
      execution.matchingExecutionCount(
        (node) => treeState.isVisible([ node.status ]) &&
                  [ node, ...execution.parents(node) ].some(
                    (ancestor) => treeState.matchesSearch(ancestor.name))),
    0));
</script>
<template>
  <div class="tree-toolbar">
    <label class="sr-only" for="test-search">Search tests</label>
    <input id="test-search" v-model="treeState.searchQuery" type="search" placeholder="Search tests" class="report-search" />
    <div class="tree-filters" aria-label="Filter test executions">
      <button type="button" class="report-button" :aria-pressed="!treeState.hasActiveStatusFilter()" @click="treeState.clearFilters()">All</button>
      <button type="button" class="report-button" :aria-pressed="treeState.showFailedAndErrored" @click="treeState.toggleShowFailedAndErrored()">Failed / Errored {{ formatCount(counts.FAILED || 0) }} / {{ formatCount(counts.ERRORED || 0) }}</button>
      <button type="button" class="report-button" :aria-pressed="treeState.showSuccessful" @click="treeState.toggleShowSuccessful()">Passed {{ formatCount(counts.SUCCESSFUL || 0) }}</button>
      <button type="button" class="report-button" :aria-pressed="treeState.showSkipped" @click="treeState.toggleShowSkipped()">Skipped {{ formatCount(counts.SKIPPED || 0) }}</button>
      <button v-if="counts.ABORTED" type="button" class="report-button" :aria-pressed="treeState.showAborted" @click="treeState.toggleShowAborted()">Aborted {{ formatCount(counts.ABORTED) }}</button>
    </div>
    <div class="tree-filter-description" aria-live="polite">
      <span>{{ treeState.showFailedAndErrored && !treeState.showSuccessful && !treeState.showSkipped && !treeState.showAborted ? "Showing failed and errored tests" : treeState.hasActiveStatusFilter() ? "Showing selected statuses" : "Showing all statuses" }}</span>
      <button v-if="treeState.hasActiveStatusFilter() || treeState.hasActiveSearch()" type="button" class="report-text-button" @click="treeState.clearFilters()">Clear filters</button>
    </div>
    <div class="tree-toolbar-actions">
      <span class="report-muted">{{ formatCount(matching) }} matching executions</span>
      <button type="button" class="report-icon-button" :aria-label="treeState.sortMode === 'alphabetical' ? 'Sort by execution order' : 'Sort alphabetically'" :aria-pressed="treeState.sortMode === 'alphabetical'" @click="treeState.toggleSortMode()"><ArrowDownAZ v-bind="defaultIconProps" /></button>
      <button type="button" class="report-icon-button" aria-label="Expand all" @click="treeState.expandAll()"><ChevronsUpDown v-bind="defaultIconProps" /></button>
      <button type="button" class="report-icon-button" aria-label="Collapse all" @click="treeState.collapseAll()"><ChevronsDownUp v-bind="defaultIconProps" /></button>
    </div>
    <span class="report-muted">Execution counts include CTest checks. Overview test counts remain unfiltered.</span>
  </div>
</template>
