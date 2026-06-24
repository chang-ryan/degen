<script setup lang="ts">
const props = defineProps<{ panel: any }>()
const score = computed(() => Math.max(0, Math.min(100, props.panel.extra.score)))

// semicircle gauge: 180deg sweep, score 0..100 -> angle -90..+90
const R = 70
const CX = 90
const CY = 90
function pt(angleDeg: number) {
  const a = ((angleDeg - 90) * Math.PI) / 180
  return [CX + R * Math.cos(a), CY + R * Math.sin(a)]
}
const arc = computed(() => {
  const a0 = 0
  const a1 = (score.value / 100) * 180
  const [x0, y0] = pt(a0)
  const [x1, y1] = pt(a1)
  const large = a1 - a0 > 180 ? 1 : 0
  return `M ${x0} ${y0} A ${R} ${R} 0 ${large} 1 ${x1} ${y1}`
})
const trackPath = computed(() => {
  const [x0, y0] = pt(0)
  const [x1, y1] = pt(180)
  return `M ${x0} ${y0} A ${R} ${R} 0 1 1 ${x1} ${y1}`
})
const color = computed(() =>
  score.value < 25 ? '#f0556b' : score.value < 45 ? '#f5b942' : score.value < 55 ? '#7c8699' : score.value < 75 ? '#2dd4a7' : '#2dd4a7',
)
const needle = computed(() => pt((score.value / 100) * 180))
</script>

<template>
  <div class="card flex flex-col gap-2">
    <div class="flex items-start justify-between">
      <h3 class="text-sm font-semibold text-slate-200">
        {{ panel.title }}
      </h3>
      <span class="chip bg-ink-800 text-muted">contrarian</span>
    </div>

    <div class="relative mx-auto">
      <svg viewBox="0 5 180 95" class="w-[200px]">
        <path :d="trackPath" fill="none" stroke="#252b3a" stroke-width="10" stroke-linecap="round" />
        <path :d="arc" fill="none" :stroke="color" stroke-width="10" stroke-linecap="round" />
        <line :x1="CX" :y1="CY" :x2="needle[0]" :y2="needle[1]" :stroke="color" stroke-width="2" />
        <circle :cx="CX" :cy="CY" r="4" :fill="color" />
      </svg>
      <div class="absolute inset-x-0 bottom-0 text-center">
        <div class="text-3xl font-bold" :style="{ color }">
          {{ Math.round(score) }}
        </div>
        <div class="text-[11px] uppercase tracking-wide text-muted">
          {{ panel.headline.label }}
        </div>
      </div>
    </div>

    <div class="mt-1 flex flex-wrap gap-1">
      <span
        v-for="(s, i) in panel.extra.subs"
        :key="i"
        class="chip bg-ink-800 text-[10px]"
        :class="String(s[1]).includes('extreme fear') ? 'text-bad' : String(s[1]).includes('fear') ? 'text-warn' : 'text-muted'"
      >
        {{ s[0] }}
      </span>
    </div>
  </div>
</template>
