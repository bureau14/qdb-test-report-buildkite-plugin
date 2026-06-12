<!-- Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/components/sidebar/ExecutionTree.vue -->
<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import TestExecution from "../common/TestExecution.ts";
import Selection from "../common/Selection.ts";
import TreeRow from "./TreeRow.vue";
import { treeStateKey } from "./TreeState.ts";
import { visibleRows } from "./VisibleTree.ts";

const ROW_HEIGHT = 24;
const OVERSCAN_ROWS = 20;

const selection = defineModel<Selection | undefined>("selection");
const props = defineProps<{ executions: TestExecution[] }>();
const treeState = inject(treeStateKey)!;
const container = ref<HTMLElement | null>(null);
const scrollTop = ref(0);
const viewportHeight = ref(600);
let resizeObserver: ResizeObserver | undefined;

const rows = computed(() => visibleRows(props.executions, treeState));
const startIndex = computed(() =>
  Math.max(0, Math.floor(scrollTop.value / ROW_HEIGHT) - OVERSCAN_ROWS),
);
const endIndex = computed(() =>
  Math.min(
    rows.value.length,
    Math.ceil((scrollTop.value + viewportHeight.value) / ROW_HEIGHT) +
      OVERSCAN_ROWS,
  ),
);
const visible = computed(() => rows.value.slice(startIndex.value, endIndex.value));
const topPadding = computed(() => startIndex.value * ROW_HEIGHT);
const bottomPadding = computed(() =>
  Math.max(0, (rows.value.length - endIndex.value) * ROW_HEIGHT),
);

function updateViewportHeight() {
  if (container.value) {
    viewportHeight.value = container.value.clientHeight || viewportHeight.value;
  }
}

function onScroll(event: Event) {
  scrollTop.value = (event.target as HTMLElement).scrollTop;
}

watch(rows, () => {
  if (container.value) {
    const maxScrollTop = Math.max(0, rows.value.length * ROW_HEIGHT - viewportHeight.value);
    if (container.value.scrollTop > maxScrollTop) {
      container.value.scrollTop = maxScrollTop;
      scrollTop.value = maxScrollTop;
    }
  }
});

onMounted(async () => {
  await nextTick();
  updateViewportHeight();
  if (container.value && typeof ResizeObserver !== "undefined") {
    resizeObserver = new ResizeObserver(updateViewportHeight);
    resizeObserver.observe(container.value);
  }
});

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
});
</script>

<template>
  <div
    v-if="rows.length"
    ref="container"
    class="h-[calc(100vh-3rem)] overflow-auto pr-2"
    @scroll="onScroll"
  >
    <div :style="{ height: `${topPadding}px` }" />
    <TreeRow
      v-for="row in visible"
      :key="row.id"
      v-model:selection="selection"
      :row="row"
    />
    <div :style="{ height: `${bottomPadding}px` }" />
  </div>
</template>
