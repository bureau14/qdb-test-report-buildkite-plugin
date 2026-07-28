<!--  Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/components/sidebar/ToolBar.vue -->
<script setup lang="ts">
import { ArrowDownAZ, ChevronsDownUp, ChevronsUpDown } from "@lucide/vue";
import ToolBarIcon from "./ToolBarIcon.vue";
import TestResultStatusIcon from "../common/TestResultStatusIcon.vue";
import { defaultIconProps } from "../common/icon.ts";
import { inject } from "vue";
import { treeStateKey } from "./TreeState.ts";

const treeState = inject(treeStateKey)!;
</script>

<template>
  <div
    class="bg-neutral-100 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-300 border-b border-neutral-200 dark:border-neutral-700 flex flex-col gap-2 px-1.5 py-2"
  >
    <label class="sr-only" for="test-search">{{ $t("toolbar.search") }}</label>
    <input
      id="test-search"
      v-model="treeState.searchQuery"
      type="search"
      :placeholder="$t('toolbar.search')"
      class="min-w-0 rounded-sm border border-neutral-300 bg-white px-2 py-1 text-sm text-neutral-900 placeholder:text-neutral-500 dark:border-neutral-600 dark:bg-neutral-900 dark:text-neutral-100 dark:placeholder:text-neutral-400"
    />
    <div class="flex flex-row">
      <div class="flex flex-row flex-1">
        <ToolBarIcon
          :selected="treeState.showSuccessful"
          :title="$t('toolbar.showSuccessful')"
          @click="treeState.toggleShowSuccessful()"
        >
          <TestResultStatusIcon
            status="SUCCESSFUL"
            v-bind="defaultIconProps"
            color="''"
          />
        </ToolBarIcon>
        <ToolBarIcon
          :selected="treeState.showFailedAndErrored"
          :title="$t('toolbar.showFailedAndErrored')"
          @click="treeState.toggleShowFailedAndErrored()"
        >
          <TestResultStatusIcon
            status="FAILED"
            v-bind="defaultIconProps"
            color="''"
          />
        </ToolBarIcon>
        <ToolBarIcon
          :selected="treeState.showSkipped"
          :title="$t('toolbar.showSkipped')"
          @click="treeState.toggleShowSkipped()"
        >
          <TestResultStatusIcon
            status="SKIPPED"
            v-bind="defaultIconProps"
            color="''"
          />
        </ToolBarIcon>
        <ToolBarIcon
          :selected="treeState.showAborted"
          :title="$t('toolbar.showAborted')"
          @click="treeState.toggleShowAborted()"
        >
          <TestResultStatusIcon
            status="ABORTED"
            v-bind="defaultIconProps"
            color="''"
          />
        </ToolBarIcon>
      </div>
      <div class="flex flex-row">
        <ToolBarIcon
          :selected="treeState.sortMode === 'alphabetical'"
          :title="
            treeState.sortMode === 'alphabetical'
              ? $t('toolbar.sortByExecutionOrder')
              : $t('toolbar.sortAlphabetically')
          "
          @click="treeState.toggleSortMode()"
        >
          <ArrowDownAZ v-bind="defaultIconProps" />
        </ToolBarIcon>
        <ToolBarIcon
          :title="$t('toolbar.expandAll')"
          @click="treeState.expandAll()"
        >
          <ChevronsUpDown v-bind="defaultIconProps" />
        </ToolBarIcon>
        <ToolBarIcon
          :title="$t('toolbar.collapseAll')"
          @click="treeState.collapseAll()"
        >
          <ChevronsDownUp v-bind="defaultIconProps" />
        </ToolBarIcon>
      </div>
    </div>
  </div>
</template>
