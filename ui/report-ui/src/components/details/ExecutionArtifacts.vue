<!-- Modified from original source; this is an original local extension. -->
<script setup lang="ts">
import { computed, ref, watch } from "vue";
import {
  Download,
  FileText,
  Server,
  Terminal,
  TriangleAlert,
} from "@lucide/vue";
import { defaultIconProps } from "../common/icon.ts";
import ArchiveDownload from "./ArchiveDownload.vue";
import { archiveMember, downloadMembers } from "./archive-download.ts";
import {
  fileLabel,
  formatFileSize,
  groupArtifacts,
} from "./artifact-groups.ts";
import type { ArtifactFile } from "./artifact-groups.ts";
/* global SourceData */

const props = defineProps<{
  artifacts: ArtifactFile[];
  sources?: SourceData[];
  title?: string;
}>();
const showEmpty = ref(false);
const showPaths = ref(false);
const busy = ref(false);
const error = ref("");
const groups = computed(() => groupArtifacts(props.artifacts));
const reports = computed(() => {
  const reportFiles = props.artifacts.filter((file) =>
    /\.xml$/i.test(file.relativePath),
  );
  const result = reportFiles.map((file) => ({
    label: "JUnit XML",
    path: file.relativePath,
    url: file.url,
  }));
  for (const source of props.sources || []) {
    const basename = source.xml.split("/").pop();
    const matches = reportFiles.some(
      (file) =>
        file.relativePath.split("/").pop() === basename &&
        (!source.jobId || file.key.includes(`/jobs/${source.jobId}/`)),
    );
    if (
      !matches &&
      !result.some(
        (item) => item.url === source.xmlUrl && item.path === source.xml,
      )
    )
      result.push({ label: "JUnit XML", path: source.xml, url: source.xmlUrl });
  }
  return result.map((item) => ({
    ...item,
    label: result.length > 1 ? item.path.split("/").pop()! : "JUnit XML",
  }));
});
const emptyCount = computed(
  () => props.artifacts.filter((file) => file.sizeBytes === 0).length,
);
const archives = computed(() => [
  ...new Set(
    props.artifacts.flatMap((file) =>
      file.url && archiveMember(file.url) ? [archiveMember(file.url)!.url] : [],
    ),
  ),
]);
const references = computed(() =>
  props.artifacts.flatMap((file) =>
    file.url && archiveMember(file.url) ? [archiveMember(file.url)!] : [],
  ),
);
const availableGroups = computed(() =>
  groups.value.filter(
    (group) => group.kind !== "report" && group.kind !== "other",
  ),
);
const otherFiles = computed(() =>
  groups.value
    .filter((group) => group.kind === "other")
    .flatMap((group) => group.files),
);
const singleExecution = computed(
  () =>
    new Set(props.artifacts.map((file) => file.executionId).filter(Boolean))
      .size <= 1,
);
function visibleFiles(files: ArtifactFile[]) {
  return files.filter((file) => showEmpty.value || file.sizeBytes !== 0);
}
watch(
  () => props.artifacts,
  () => {
    error.value = "";
    showEmpty.value = false;
  },
);
async function downloadAll() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await downloadMembers(references.value, "execution-artifacts.zip");
  } catch (reason) {
    error.value = `${reason instanceof Error ? reason.message : "Download failed."} Use the job ZIP under Other job artifacts, or retry.`;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section
    v-if="artifacts.length || reports.length"
    class="px-4 pb-5"
    aria-label="Execution artifacts"
  >
    <div class="flex flex-wrap items-center justify-between gap-3 mt-4 mb-3">
      <div>
        <h3 class="font-semibold">
          {{ title || "Suite execution artifacts" }}
        </h3>
        <p class="text-xs text-neutral-500 dark:text-neutral-400">
          {{
            title
              ? "Files belonging to this selection"
              : "Shared by all cases in this suite"
          }}
        </p>
      </div>
      <button
        v-if="references.length && references.length === artifacts.length"
        type="button"
        class="inline-flex items-center gap-2 border border-neutral-300 dark:border-neutral-600 rounded px-3 py-1.5 text-sm disabled:opacity-50 hover:bg-neutral-100 dark:hover:bg-neutral-800"
        :disabled="busy"
        :aria-busy="busy"
        @click="downloadAll"
      >
        <Download v-bind="defaultIconProps" />{{
          busy ? "Preparing download…" : "Download all"
        }}
      </button>
    </div>
    <component :is="reports.length > 1 ? 'details' : 'div'">
      <summary v-if="reports.length > 1" class="cursor-pointer py-3 text-sm">
        Reports · {{ reports.length }}
      </summary>
      <div
        v-for="report in reports"
        :key="report.url || report.path"
        class="flex items-center flex-wrap gap-2 py-2 text-sm"
      >
        <FileText v-bind="defaultIconProps" class="text-neutral-500" />
        <ArchiveDownload
          v-if="report.url && archiveMember(report.url)"
          :reference="archiveMember(report.url)!"
          :label="report.label"
          compact
        />
        <a
          v-else-if="report.url"
          :href="report.url"
          target="_blank"
          rel="noopener noreferrer"
          class="text-blue-600 dark:text-blue-400 hover:underline"
          >{{ report.label }}</a
        ><span v-else>{{ report.path }}</span>
      </div>
    </component>
    <template v-for="group in availableGroups" :key="group.id">
      <details
        v-if="visibleFiles(group.files).length"
        :open="
          group.kind === 'crash' || (group.kind === 'runner' && singleExecution)
        "
        class="border-t border-neutral-200 dark:border-neutral-700"
        :class="{ 'text-red-700 dark:text-red-400': group.kind === 'crash' }"
      >
        <summary class="cursor-pointer py-3 text-sm">
          <span class="inline-flex items-center gap-2"
            ><TriangleAlert
              v-if="group.kind === 'crash'"
              v-bind="defaultIconProps"
            /><Terminal
              v-else-if="group.kind === 'runner'"
              v-bind="defaultIconProps"
            /><Server
              v-else-if="group.kind === 'server'"
              v-bind="defaultIconProps"
            />{{ group.title
            }}<span class="text-xs text-neutral-500 dark:text-neutral-400">{{
              visibleFiles(group.files).length
            }}</span></span
          >
        </summary>
        <div class="pl-5 pb-3">
          <div
            v-for="file in visibleFiles(group.files)"
            :key="file.key + file.relativePath"
            class="py-1.5 text-sm"
          >
            <div class="flex items-start gap-3 justify-between">
              <span :title="file.relativePath" class="min-w-0 break-all"
                ><ArchiveDownload
                  v-if="file.url && archiveMember(file.url)"
                  :reference="archiveMember(file.url)!"
                  :label="fileLabel(file)"
                  compact
                /><a
                  v-else-if="file.url"
                  :href="file.url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="text-blue-600 dark:text-blue-400 hover:underline"
                  >{{ fileLabel(file) }}</a
                ><span v-else>{{ fileLabel(file) }}</span></span
              ><span
                class="text-xs text-neutral-500 dark:text-neutral-400 whitespace-nowrap tabular-nums"
                >{{ formatFileSize(file.sizeBytes) }}</span
              >
            </div>
            <p
              v-if="showPaths"
              class="text-xs font-mono text-neutral-500 dark:text-neutral-400 break-all mt-1"
            >
              {{ file.relativePath }}
            </p>
          </div>
        </div>
      </details>
    </template>
    <details
      v-if="archives.length || otherFiles.length"
      class="border-t border-neutral-200 dark:border-neutral-700"
    >
      <summary
        class="cursor-pointer py-3 text-xs text-neutral-500 dark:text-neutral-400"
      >
        Other job artifacts · Full job ZIPs
      </summary>
      <div class="pl-5 pb-3">
        <div
          v-for="file in visibleFiles(otherFiles)"
          :key="file.key + file.relativePath"
          class="py-1.5"
        >
          <ArchiveDownload
            v-if="file.url && archiveMember(file.url)"
            :reference="archiveMember(file.url)!"
            :label="fileLabel(file)"
            compact
          />
          <a
            v-else-if="file.url"
            :href="file.url"
            target="_blank"
            rel="noopener noreferrer"
            class="text-sm text-blue-600 dark:text-blue-400"
            >{{ fileLabel(file) }}</a
          ><span v-else>{{ fileLabel(file) }}</span>
        </div>
        <a
          v-for="(archive, index) in archives"
          :key="archive"
          :href="archive"
          target="_blank"
          rel="noopener noreferrer"
          class="block py-1 text-sm text-blue-600 dark:text-blue-400 hover:underline"
          >Download full job ZIP{{
            archives.length > 1 ? ` ${index + 1}` : ""
          }}</a
        >
      </div>
    </details>
    <div
      class="flex flex-wrap justify-between gap-3 border-t border-neutral-200 dark:border-neutral-700 pt-3 text-xs text-neutral-500 dark:text-neutral-400"
    >
      <div class="flex flex-wrap gap-4">
        <label class="inline-flex items-center gap-1.5"
          ><input v-model="showEmpty" type="checkbox" />Show empty files</label
        ><label class="inline-flex items-center gap-1.5"
          ><input v-model="showPaths" type="checkbox" />Show paths</label
        >
      </div>
      <span
        >{{ artifacts.length }} files<span v-if="!showEmpty && emptyCount">
          · {{ emptyCount }} empty hidden</span
        ></span
      >
    </div>
    <p
      v-if="error"
      role="alert"
      class="text-sm text-red-600 dark:text-red-400 mt-3"
    >
      {{ error }}
    </p>
  </section>
</template>
