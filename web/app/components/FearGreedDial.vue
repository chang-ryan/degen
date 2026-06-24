<script setup lang="ts">
const props = defineProps<{ panel: any }>()
const score = computed(() => Math.max(0, Math.min(100, props.panel.extra.score)))

// Standard speedometer: 0 = extreme fear (LEFT) → 100 = extreme greed (RIGHT),
// arc over the top, flat side down. The needle + fill sit low-left for fear.
const R = 70
const CX = 90
const CY = 80 // baseline; the semicircle bulges up (y < CY)

// score 0..100 → a point on the upper semicircle (180° on the left → 0° on the right).
function pt(s: number): [number, number] {
  const rad = ((180 - (s / 100) * 180) * Math.PI) / 180
  return [CX + R * Math.cos(rad), CY - R * Math.sin(rad)]
}
// top-semicircle arc from score s0 → s1 (s0 ≤ s1); sweep=1 draws over the top
function arcPath(s0: number, s1: number): string {
  const [x0, y0] = pt(s0)
  const [x1, y1] = pt(s1)
  return `M ${x0} ${y0} A ${R} ${R} 0 0 1 ${x1} ${y1}`
}

const trackPath = computed(() => arcPath(0, 100))
const valuePath = computed(() => arcPath(0, score.value))
const needle = computed(() => pt(score.value))
const color = computed(() =>
  score.value < 25 ? '#f0556b' : score.value < 45 ? '#f5b942' : score.value < 55 ? '#7c8699' : '#2dd4a7',
)
</script>

<template>
  <div class="card flex flex-col gap-3">
    <div class="flex items-start justify-between">
      <h3 class="text-sm font-semibold text-slate-200">
        {{ panel.title }}
      </h3>
      <span class="chip bg-ink-800 text-muted">contrarian</span>
    </div>

    <!-- gauge -->
    <svg viewBox="6 0 168 96" class="mx-auto w-[220px]">
      <path :d="trackPath" fill="none" stroke="#252b3a" stroke-width="11" stroke-linecap="round" />
      <path :d="valuePath" fill="none" :stroke="color" stroke-width="11" stroke-linecap="round" />
      <line :x1="CX" :y1="CY" :x2="needle[0]" :y2="needle[1]" :stroke="color" stroke-width="2.5" />
      <circle :cx="CX" :cy="CY" r="4.5" :fill="color" />
      <text x="16" y="94" fill="#5b6577" font-size="9">fear</text>
      <text x="146" y="94" fill="#5b6577" font-size="9">greed</text>
    </svg>

    <!-- value text, BELOW the gauge -->
    <div class="text-center leading-none">
      <div class="text-3xl font-bold" :style="{ color }">
        {{ Math.round(score) }}
      </div>
      <div class="mt-1 text-[11px] uppercase tracking-wide text-muted">
        {{ panel.headline.label }}
      </div>
    </div>

    <!-- sub-index badges, BELOW the text -->
    <div class="flex flex-wrap justify-center gap-1">
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
