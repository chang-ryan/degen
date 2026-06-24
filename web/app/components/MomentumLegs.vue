<script setup lang="ts">
defineProps<{ panel: any }>()
// off-hi is negative (drawdown); 5d signed (basing >= 0). Scale bars to a fixed range.
function w(v: number, max: number) {
  return Math.min(100, (Math.abs(v) / max) * 100)
}
</script>

<template>
  <div class="card flex flex-col gap-3" :class="`card-${panel.status}`">
    <div class="flex items-start justify-between">
      <h3 class="text-sm font-semibold text-slate-200">
        {{ panel.title }}
      </h3>
      <div class="text-right">
        <span class="text-lg font-bold" :class="panel.status === 'bad' ? 'text-bad' : 'text-warn'">{{ panel.headline.value }}</span>
        <span class="ml-1 text-[11px] text-muted">basing</span>
      </div>
    </div>

    <div class="flex flex-col gap-2">
      <div v-for="(leg, i) in panel.extra.legs" :key="i" class="grid grid-cols-[120px_1fr_46px] items-center gap-2 text-[11px]">
        <div class="truncate">
          <div class="text-slate-300">
            {{ leg.label }}
          </div>
          <div class="font-mono text-[10px] text-muted">
            {{ leg.pair }}
          </div>
        </div>
        <!-- off-hi drawdown bar (red, grows left->right by magnitude) -->
        <div class="h-3 overflow-hidden rounded bg-ink-800">
          <div class="h-full rounded bg-bad/70" :style="{ width: `${w(leg.offhi, 12)}%` }" />
        </div>
        <!-- 5d basing indicator -->
        <div class="text-right font-mono tabular-nums" :class="leg.d5 >= 0 ? 'text-good' : 'text-bad'">
          {{ leg.d5 >= 0 ? '+' : '' }}{{ leg.d5 }}%
        </div>
      </div>
    </div>

    <div class="flex items-center justify-between border-t border-ink-700/40 pt-2 font-mono text-[11px] text-muted">
      <span>off-hi · 5d basing</span>
      <span>VIX {{ panel.extra.vix }} · VVIX <span :class="panel.extra.vvix > 100 ? 'text-bad' : 'text-slate-300'">{{ panel.extra.vvix }}</span></span>
    </div>
    <p class="text-[11px] leading-snug text-slate-500">
      {{ panel.note }}
    </p>
  </div>
</template>
