<script setup lang="ts">
import { ref, watch } from "vue";
import { downloadMember } from "./archive-download.ts";
import type { ArchiveMember } from "./archive-download.ts";

const props = defineProps<{ reference: ArchiveMember }>();
const busy = ref(false);
const error = ref("");

watch(
  () => props.reference,
  () => {
    error.value = "";
  },
);

async function download() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await downloadMember(props.reference);
  } catch {
    error.value =
      "Could not download this file. Retry, or download the ZIP below.";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="text-sm">
    <button
      type="button"
      :disabled="busy"
      :aria-busy="busy"
      class="text-blue-600 dark:text-blue-500 hover:underline disabled:opacity-50"
      @click="download"
    >
      {{
        busy
          ? "Preparing download…"
          : `Download ${reference.member.split("/").pop()}`
      }}
    </button>
    <pre class="whitespace-pre-wrap break-all">{{ reference.member }}</pre>
    <a
      :href="reference.url"
      target="_blank"
      rel="noopener noreferrer"
      class="text-blue-600 dark:text-blue-500 hover:underline"
      >Download ZIP</a
    >
    <p v-if="error" role="alert" class="text-red-600 dark:text-red-500">
      {{ error }}
    </p>
  </div>
</template>
