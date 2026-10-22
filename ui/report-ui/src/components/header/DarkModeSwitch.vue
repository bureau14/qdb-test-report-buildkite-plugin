<script setup lang="ts">
import {MoonStar, Sun} from "@lucide/vue";
import {BasicColorSchema, useDark, useToggle} from "@vueuse/core";

import {defaultIconProps} from "../common/icon.ts";

const dark = useDark({
  onChanged(
    _dark: boolean,
    defaultHandler: (mode: BasicColorSchema) => void,
    mode: BasicColorSchema,
  ) {
    defaultHandler(mode);
    // Toggle color of scrollbars
    document.body.style.colorScheme = mode;
  },
});
const toggleDark = useToggle(dark);
</script>

<template>
  <button
    type="button"
    class="report-icon-button"
    role="switch"
    aria-label="Dark mode"
    :aria-checked="dark"
    @click="toggleDark()"
  >
    <Sun v-bind="defaultIconProps" class="dark:hidden" />
    <MoonStar v-bind="defaultIconProps" class="hidden dark:block" />
  </button>
</template>
