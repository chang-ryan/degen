<script setup lang="ts">
const props = defineProps<{ dates: string[], current: string }>()
const emit = defineEmits<{ (e: 'select', date: string): void }>()

const idx = computed(() => props.dates.indexOf(props.current))
const hasPrev = computed(() => idx.value < props.dates.length - 1) // dates desc -> prev is older
const hasNext = computed(() => idx.value > 0)
const isToday = computed(() => idx.value === 0)

function go(delta: number) {
  const next = props.dates[idx.value + delta]
  if (next)
    emit('select', next)
}
const pretty = computed(() =>
  new Date(`${props.current}T00:00:00`).toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }),
)
</script>

<template>
  <div class="flex items-center gap-2">
    <button
      class="rounded-md border border-ink-700 bg-ink-850 px-2 py-1 text-sm text-slate-300 enabled:hover:bg-ink-800 disabled:opacity-30"
      :disabled="!hasPrev"
      @click="go(1)"
    >
      ‹
    </button>

    <div class="min-w-[190px] text-center">
      <div class="font-mono text-sm font-semibold text-slate-100">
        {{ pretty }}
      </div>
      <div class="text-[10px] uppercase tracking-wide" :class="isToday ? 'text-good' : 'text-muted'">
        {{ isToday ? 'latest' : 'historical' }}
      </div>
    </div>

    <button
      class="rounded-md border border-ink-700 bg-ink-850 px-2 py-1 text-sm text-slate-300 enabled:hover:bg-ink-800 disabled:opacity-30"
      :disabled="!hasNext"
      @click="go(-1)"
    >
      ›
    </button>

    <button
      v-if="!isToday"
      class="ml-1 rounded-md border border-good/40 bg-good/10 px-2 py-1 text-xs text-good hover:bg-good/20"
      @click="emit('select', dates[0])"
    >
      today
    </button>
  </div>
</template>
