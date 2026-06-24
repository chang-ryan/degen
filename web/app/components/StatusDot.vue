<script setup lang="ts">
defineProps<{ state?: string }>()
const map: Record<string, string> = {
  good: 'bg-good shadow-[0_0_8px_0] shadow-good/60',
  warn: 'bg-warn shadow-[0_0_8px_0] shadow-warn/60',
  bad: 'bg-bad shadow-[0_0_8px_0] shadow-bad/60',
  neutral: 'bg-muted',
}
</script>

<template>
  <span class="inline-block h-2 w-2 rounded-full" :class="map[state || 'neutral']" />
</template>
