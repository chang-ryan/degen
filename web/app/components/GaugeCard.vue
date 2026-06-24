<script setup lang="ts">
defineProps<{ panel: any }>()

const stateText: Record<string, string> = {
  good: 'text-good',
  warn: 'text-warn',
  bad: 'text-bad',
  neutral: 'text-muted',
}
const cardClass: Record<string, string> = {
  good: 'card-good',
  warn: 'card-warn',
  bad: 'card-bad',
  neutral: '',
}
</script>

<template>
  <div class="card flex flex-col gap-3" :class="cardClass[panel.status]">
    <!-- header -->
    <div class="flex items-start justify-between gap-2">
      <h3 class="text-sm font-semibold text-slate-200">
        {{ panel.title }}
      </h3>
      <StatusDot :state="panel.status" />
    </div>

    <!-- headline -->
    <div v-if="panel.headline" class="leading-tight">
      <div class="flex items-baseline gap-2">
        <span class="text-2xl font-bold tracking-tight" :class="stateText[panel.status]">
          {{ panel.headline.value }}
        </span>
        <span class="text-xs text-muted">{{ panel.headline.label }}</span>
      </div>
      <div v-if="panel.headline.sub" class="mt-0.5 text-[11px] text-slate-400">
        {{ panel.headline.sub }}
      </div>
    </div>

    <!-- rows -->
    <div v-if="panel.rows?.length" class="flex flex-col gap-1 font-mono text-[12px]">
      <div
        v-for="(r, i) in panel.rows"
        :key="i"
        class="flex items-center justify-between gap-3 border-t border-ink-700/40 py-1 first:border-t-0"
      >
        <span class="text-slate-400">{{ r.label }}</span>
        <span class="flex items-center gap-2 tabular-nums">
          <span :class="r.state ? stateText[r.state] : 'text-slate-200'">{{ r.value }}</span>
          <span v-if="r.delta" class="text-[10px] text-muted">{{ r.delta }}</span>
        </span>
      </div>
    </div>

    <!-- footnote -->
    <p v-if="panel.note" class="mt-auto pt-1 text-[11px] leading-snug text-slate-500">
      {{ panel.note }}
    </p>
  </div>
</template>
