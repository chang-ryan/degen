<script setup lang="ts">
const props = defineProps<{ posture: any }>()
const open = computed(() => props.posture.window === 'OPEN')
const gateText: Record<string, string> = { good: 'text-good', warn: 'text-warn', bad: 'text-bad' }
const gateBg: Record<string, string> = { good: 'bg-good', warn: 'bg-warn', bad: 'bg-bad' }
</script>

<template>
  <div
    class="card flex flex-col gap-4 border-l-4 lg:flex-row lg:items-center lg:justify-between"
    :class="open ? 'border-l-good' : 'border-l-bad'"
  >
    <!-- window verdict -->
    <div class="flex items-center gap-4">
      <div>
        <div class="section-label">
          Dip-buy window
        </div>
        <div class="text-3xl font-black tracking-tight" :class="open ? 'text-good' : 'text-bad'">
          {{ posture.window }}
        </div>
      </div>
      <!-- three gates -->
      <div class="flex gap-2">
        <div
          v-for="(g, i) in posture.gates"
          :key="i"
          class="flex min-w-[108px] flex-col gap-1 rounded-lg border border-ink-700/60 bg-ink-900 px-3 py-2"
        >
          <div class="flex items-center gap-1.5">
            <span class="h-2.5 w-2.5 rounded-full" :class="gateBg[g.state]" />
            <span class="text-[11px] font-medium text-slate-300">{{ g.label }}</span>
          </div>
          <span class="font-mono text-[10px]" :class="gateText[g.state]">{{ g.detail }}</span>
        </div>
      </div>
    </div>

    <!-- de-risk triggers -->
    <div class="flex flex-col gap-1.5">
      <div class="section-label">
        De-risk triggers
      </div>
      <div class="flex flex-wrap gap-1.5">
        <span
          v-for="(t, i) in posture.triggers"
          :key="i"
          class="chip border"
          :class="t.active ? 'border-bad/50 bg-bad/15 text-bad' : 'border-ink-700 bg-ink-900 text-muted'"
          :title="t.detail"
        >
          <span class="h-1.5 w-1.5 rounded-full" :class="t.active ? 'bg-bad' : 'bg-ink-700'" />
          {{ t.label }}
          <span class="opacity-70">· {{ t.detail }}</span>
        </span>
      </div>
    </div>
  </div>
</template>
