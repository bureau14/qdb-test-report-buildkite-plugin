<script setup lang="ts">
import {Timer} from "@lucide/vue";

import {defaultIconProps} from "../common/icon.ts";
import {formatDuration} from "../common/presentation.ts";

defineProps<{millis : number; label?: string}>();
</script>
<template>
  <span class="duration-label"><Timer v-bind="defaultIconProps" /><span v-if="label">{{ label }}:</span>{{ formatDuration(millis) }}</span>
</template>
