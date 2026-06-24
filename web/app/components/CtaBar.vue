<script setup lang="ts">
const props = defineProps<{ panel: any }>()
// Levels are below spot; dist = % above the level. Show spot marker + thresholds on a track.
const maxDist = computed(() => Math.max(14, ...props.panel.extra.levels.map((l: any) => l.dist)))
</script>

<template>
  <div class="card flex flex-col gap-3" :class="`card-${panel.status}`">
    <div class="flex items-start justify-between">
      <h3 class="text-sm font-semibold text-slate-200">
        {{ panel.title }}
      </h3>
      <div class="text-right">
        <span class="text-lg font-bold" :class="`text-${panel.status === 'good' ? 'good' : panel.status}`">{{ panel.headline.value }}</span>
        <span class="ml-1 text-[11px] text-muted">to short</span>
      </div>
    </div>

    <div class="font-mono text-[11px] text-muted">
      SPX spot {{ panel.headline.sub.replace('SPX ', '') }}
    </div>

    <!-- horizontal distance track: spot on the right, levels approach from below -->
    <div class="relative mt-1 h-16">
      <div class="absolute inset-x-0 top-7 h-1 rounded bg-ink-700" />
      <!-- spot marker (0% reference, right edge) -->
      <div class="absolute top-3 right-0 flex flex-col items-center">
        <span class="text-[10px] text-slate-300">spot</span>
        <span class="mt-1 h-5 w-0.5 bg-slate-300" />
      </div>
      <!-- level markers -->
      <div
        v-for="(l, i) in panel.extra.levels"
        :key="i"
        class="absolute top-3 flex flex-col items-center"
        :style="{ left: `${100 - (l.dist / maxDist) * 100}%` }"
      >
        <span class="mb-1 h-5 w-0.5" :class="l.name === 'short' ? 'bg-bad' : 'bg-warn'" />
        <span class="text-[9px]" :class="l.name === 'short' ? 'text-bad' : 'text-warn'">{{ l.name }}</span>
        <span class="font-mono text-[9px] text-muted">+{{ l.dist }}%</span>
      </div>
    </div>

    <p class="text-[11px] leading-snug text-slate-500">
      {{ panel.note }}
    </p>
  </div>
</template>
