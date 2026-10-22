<script setup lang="ts">
import {computed} from "vue";

import {valueMismatch} from "../common/report-presentation.ts";

const props = defineProps<{reason : string; status : string}>();
const mismatch = computed(() => valueMismatch(props.reason));
</script>

<template>
  <section v-if="reason" class="test-reason" :data-status="status" aria-label="Test reason">
    <h3>{{ mismatch ? 'Value mismatch · row ' + mismatch.row : status === 'SKIPPED' ? 'Skip reason' : status === 'ERRORED' ? 'Execution error' : 'Failure reason' }}</h3>
    <template v-if="mismatch">
      <div class="value-comparison">
        <div><span>Expected</span><code class="expected-value">{{ mismatch.expected }}</code></div>
        <div><span>Actual</span><code class="actual-value">{{ mismatch.actual }}</code></div>
      </div>
      <details class="raw-reason"><summary>Raw message</summary><p>{{ reason }}</p></details>
    </template>
    <p v-else>{{ reason }}</p>
  </section>
</template>
