<script setup lang="ts">
import {ArrowDown, ArrowUp} from "@lucide/vue";
import {computed} from "vue";

import {defaultIconProps} from "../common/icon.ts";
import Selection from "../common/Selection.ts";

const selection = defineModel<Selection|undefined>("selection");
const props = defineProps<{problems : Selection[]}>();
const index = computed(
  () => props.problems.findIndex(
    (problem) => problem.execution.id === selection.value?.execution.id &&
                 problem.item.id === selection.value?.item.id));
function navigate(direction: number) {
  const start = index.value < 0 ? (direction > 0 ? -1 : 0) : index.value;
  selection.value = props.problems[(start + direction + props.problems.length) %
                                   props.problems.length];
}
</script>
<template>
  <nav v-if="problems.length" class="failure-navigation" aria-label="Failure navigation">
    <span class="report-muted">{{ index >= 0 ? 'Problem ' + (index + 1) + ' of ' + problems.length : problems.length + ' failed / errored executions' }}</span>
    <button type="button" class="report-button" @click="navigate(-1)"><ArrowUp v-bind="defaultIconProps" />Previous failure</button>
    <button type="button" class="report-button" @click="navigate(1)">Next failure<ArrowDown v-bind="defaultIconProps" /></button>
  </nav>
</template>
