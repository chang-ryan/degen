<script setup lang="ts">
const props = defineProps<{ panel: any }>()
// Derive the meter from the actual signal rows so the red segments + the "N/6"
// count can never disagree with the green/red dots below them.
const rows = computed(() => props.panel.rows ?? [])
const available = computed(() => props.panel.extra?.available ?? rows.value.length)
const stress = computed(() => rows.value.filter((r: any) => r.state === 'bad').length)
</script>

<template>
  <div class="card card-warn flex flex-col gap-3">
    <div class="flex items-start justify-between">
      <h3 class="text-sm font-semibold text-slate-200">
        {{ panel.title }}
      </h3>
      <span class="chip bg-ink-800 text-muted">{{ panel.headline.sub }}</span>
    </div>

    <!-- stress segments -->
    <div class="flex items-end gap-2">
      <div class="text-3xl font-bold text-slate-100">
        {{ stress }}<span class="text-base text-muted">/{{ available }}</span>
      </div>
      <div class="mb-1.5 flex flex-1 gap-1">
        <span
          v-for="i in available"
          :key="i"
          class="h-2 flex-1 rounded-sm"
          :class="i <= stress ? 'bg-bad' : 'bg-good/60'"
        />
      </div>
    </div>

    <div class="flex flex-col gap-1 font-mono text-[12px]">
      <div
        v-for="(r, i) in panel.rows"
        :key="i"
        class="flex items-center justify-between gap-2 border-t border-ink-700/40 py-1 first:border-t-0"
      >
        <span class="flex items-center gap-1.5 text-slate-400"><StatusDot :state="r.state" />{{ r.label }}</span>
        <span class="flex items-center gap-2 tabular-nums text-slate-200">
          {{ r.value }}<span v-if="r.delta" class="text-[10px] text-muted">{{ r.delta }}</span>
        </span>
      </div>
    </div>

    <p class="text-[11px] leading-snug text-slate-500">
      {{ panel.note }}
    </p>
  </div>
</template>
