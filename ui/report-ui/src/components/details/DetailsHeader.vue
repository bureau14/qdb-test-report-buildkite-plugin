<script setup lang="ts">
defineProps<{title : string}>();
</script>
<template>
  <header class="details-heading"><slot name="above" /><h2>{{ title }}</h2><slot name="below" /></header>
</template>
