<script setup lang="ts">
const route = useRoute()
const router = useRouter()

const { data: meta } = await useFetch('/api/briefs')
const latest = computed(() => meta.value?.dates?.[0])

// The viewed date comes from ?date=YYYY-MM-DD (permalinkable). No param → today
// (the latest day). An unknown date falls back to today rather than 404-ing.
const current = computed(() => {
  const q = route.query.date
  const dates = meta.value?.dates ?? []
  return typeof q === 'string' && dates.includes(q) ? q : (latest.value ?? 'latest')
})

const { data: brief, pending } = await useFetch(() => `/api/briefs/${current.value}`, {
  watch: [current],
})

function select(date: string) {
  // today → clean URL (no query); any other day → ?date=
  router.push({ query: date === latest.value ? {} : { date } })
}

// Minimal inline-markdown for the hand-authored synopsis (bold / italic / code).
// Content is self-authored (not user input), so v-html is safe here.
function mdInline(text: string): string {
  const esc = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  return esc
    .replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold text-slate-100">$1</strong>')
    .replace(/`([^`]+)`/g, '<code class="rounded bg-ink-800 px-1 py-0.5 text-[11px] text-slate-300">$1</code>')
    .replace(/(^|[^_])_([^_]+)_/g, '$1<em class="text-slate-400">$2</em>')
}

const clockA = computed(() => brief.value?.groups?.clockA ?? [])
const clockB = computed(() => brief.value?.groups?.clockB ?? [])
const magnitude = computed(() => brief.value?.groups?.magnitude ?? [])
const backdrop = computed(() => brief.value?.groups?.backdrop ?? [])
const header = computed(() => brief.value?.groups?.header ?? [])
</script>

<template>
  <div class="min-h-screen bg-ink-950 px-4 py-5 lg:px-8">
    <div class="mx-auto max-w-[1400px]">
      <!-- top bar -->
      <header class="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div class="flex items-baseline gap-3">
          <h1 class="text-lg font-black tracking-tight text-slate-100">
            degen<span class="text-good">.</span>gauges
          </h1>
          <span class="hidden text-xs text-muted sm:inline">macro-top instrumentation · is the cycle topping?</span>
        </div>
        <DatePager v-if="meta?.dates" :dates="meta.dates" :current="current" @select="select" />
      </header>

      <div v-if="brief" class="flex flex-col gap-5">
        <!-- posture -->
        <PostureBanner :posture="brief.posture" />

        <!-- synopsis + what changed -->
        <section class="grid items-start gap-4 lg:grid-cols-[1fr_300px]">
          <div class="card">
            <div class="section-label mb-2">
              Synopsis
            </div>
            <div class="space-y-3 text-[13px] leading-relaxed text-slate-300">
              <p v-for="(para, i) in brief.synopsis.split('\n\n')" :key="i" v-html="mdInline(para)" />
            </div>
          </div>
          <div class="card card-warn">
            <div class="section-label mb-2">
              What changed <span class="text-muted">· vs prior</span>
            </div>
            <ul class="flex flex-col gap-1.5 font-mono text-[12px]">
              <li v-for="(c, i) in brief.what_changed" :key="i" class="flex items-center gap-2 text-slate-300">
                <span class="h-1 w-1 rounded-full bg-warn" />{{ c }}
              </li>
            </ul>
          </div>
        </section>

        <!-- dials -->
        <section class="grid gap-4 md:grid-cols-2 lg:grid-cols-[1fr_360px]">
          <PanelRenderer v-for="p in header" :key="p.key" :panel="p" />
        </section>

        <!-- two clocks -->
        <section class="grid gap-4 lg:grid-cols-2">
          <div class="flex flex-col gap-3">
            <div class="flex items-center gap-2">
              <span class="section-label">Clock A · ROI / demand</span>
              <span class="h-px flex-1 bg-ink-700" />
              <span class="text-[10px] text-muted">does revenue show up first?</span>
            </div>
            <div class="grid gap-4 sm:grid-cols-2">
              <PanelRenderer v-for="p in clockA" :key="p.key" :panel="p" />
            </div>
          </div>
          <div class="flex flex-col gap-3">
            <div class="flex items-center gap-2">
              <span class="section-label">Clock B · credit</span>
              <span class="h-px flex-1 bg-ink-700" />
              <span class="text-[10px] text-muted">the leading edge / the fuse</span>
            </div>
            <div class="grid gap-4 sm:grid-cols-2">
              <PanelRenderer
                v-for="p in clockB"
                :key="p.key"
                :panel="p"
                :class="p.wide ? 'sm:col-span-2' : ''"
              />
            </div>
          </div>
        </section>

        <!-- magnitude -->
        <section class="flex flex-col gap-3">
          <div class="flex items-center gap-2">
            <span class="section-label">Magnitude · the payload, not the fuse</span>
            <span class="h-px flex-1 bg-ink-700" />
            <span class="text-[10px] text-muted">how violent the unwind, if it comes</span>
          </div>
          <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <PanelRenderer v-for="p in magnitude" :key="p.key" :panel="p" />
          </div>
        </section>

        <!-- backdrop -->
        <section class="flex flex-col gap-3">
          <div class="flex items-center gap-2">
            <span class="section-label">Backdrop · environment & themes</span>
            <span class="h-px flex-1 bg-ink-700" />
          </div>
          <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <PanelRenderer v-for="p in backdrop" :key="p.key" :panel="p" />
          </div>
        </section>

        <footer class="py-6 text-center text-[11px] text-muted">
          gauges, not verdicts · instrument forced-selling, don't time tops · POC seed data
        </footer>
      </div>

      <div v-else class="py-20 text-center text-muted">
        {{ pending ? 'loading…' : 'no brief' }}
      </div>
    </div>
  </div>
</template>
