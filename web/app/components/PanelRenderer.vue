<script setup lang="ts">
import BreadthMeter from './BreadthMeter.vue'
import CtaBar from './CtaBar.vue'
import FearGreedDial from './FearGreedDial.vue'
import GaugeCard from './GaugeCard.vue'
import MomentumLegs from './MomentumLegs.vue'
import StressMeter from './StressMeter.vue'

const props = defineProps<{ panel: any }>()

const map: Record<string, any> = {
  dial: FearGreedDial,
  stress: StressMeter,
  legs: MomentumLegs,
  cta: CtaBar,
  breadth: BreadthMeter,
  metric: GaugeCard,
}
const cmp = computed(() => map[props.panel.kind] || GaugeCard)
</script>

<template>
  <component :is="cmp" :panel="panel" />
</template>
