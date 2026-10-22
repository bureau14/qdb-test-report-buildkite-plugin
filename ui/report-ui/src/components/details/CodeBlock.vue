<script setup lang="ts">
import {Check, Copy} from "@lucide/vue";
import {useClipboard} from "@vueuse/core";
import {computed, ref, watch} from "vue";

import {defaultIconProps} from "../common/icon.ts";

const props = defineProps<{content : string}>();
const source = computed(() => props.content);
const {copy, copied, isSupported} = useClipboard({source});
const wrapped = ref(true);
const expanded = ref(false);
const truncated =
  computed(() => /output truncated|truncated from/i.test(props.content));
watch(source, () => {
  expanded.value = false;
});
</script>
<template>
  <div class="diagnostic-output">
    <div class="diagnostic-toolbar">
      <span class="report-muted">{{ content.split('\n').length }} lines</span>
      <button type="button" class="report-button" :aria-pressed="wrapped" @click="wrapped = !wrapped">Wrap lines</button>
      <button type="button" class="report-button" :aria-expanded="expanded" @click="expanded = !expanded">{{ expanded ? 'Collapse' : 'Expand' }}</button>
      <button v-if="isSupported" type="button" class="report-button" @click="copy(source)"><Check v-if="copied" v-bind="defaultIconProps" /><Copy v-else v-bind="defaultIconProps" />{{ copied ? 'Copied' : 'Copy' }}</button>
    </div>
    <p v-if="truncated" class="truncation-notice">Output was truncated. Download the complete log from the execution artifacts.</p>
    <pre :class="{ 'wrap-output': wrapped, 'expanded-output': expanded }"><code>{{ content }}</code></pre>
  </div>
</template>
