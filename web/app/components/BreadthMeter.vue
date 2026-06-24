<script setup lang="ts">
defineProps<{ panel: any }>()
function color(v: number) {
  return v >= 60 ? 'bg-good' : v >= 50 ? 'bg-warn' : 'bg-bad'
}
</script>

<template>
  <div class="card flex flex-col gap-3" :class="`card-${panel.status}`">
    <div class="flex items-start justify-between">
      <h3 class="text-sm font-semibold text-slate-200">
        {{ panel.title }}
      </h3>
      <span class="chip bg-ink-800 text-muted">n=502</span>
    </div>

    <div class="flex flex-col gap-3">
      <div v-for="m in [{ k: '% above 50dma', v: panel.extra.pct50 }, { k: '% above 200dma', v: panel.extra.pct200 }]" :key="m.k">
        <div class="mb-1 flex justify-between text-[11px]">
          <span class="text-slate-400">{{ m.k }}</span>
          <span class="font-mono tabular-nums text-slate-200">{{ m.v }}%</span>
        </div>
        <div class="h-2.5 overflow-hidden rounded-full bg-ink-800">
          <div class="h-full rounded-full" :class="color(m.v)" :style="{ width: `${m.v}%` }" />
        </div>
      </div>
    </div>

    <p class="mt-auto text-[11px] leading-snug text-slate-500">
      {{ panel.note }}
    </p>
  </div>
</template>
