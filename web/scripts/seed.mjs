// Seed web/data/briefs.db from transcribed brief data.
//
// 2026-06-23 is a full, faithful transcription of docs/daily/2026-06-23.md
// (synopsis privacy-cleaned for a general audience — no accounts/institutions/sizing).
// 2026-06-21 / 06-22 reuse slow-moving cards but carry each day's REAL dynamic
// values (vix, breadth, F&G, STRC, mag7, legs, EWY) from data/snapshots/*.json,
// so date pagination shows genuine movement. The eventual Python generator will
// emit this exact panel shape via a dataclass->panel mapper.

import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const DATA_DIR = resolve(here, '../data')
mkdirSync(DATA_DIR, { recursive: true })
const DB_PATH = resolve(DATA_DIR, 'briefs.db')

// ---- slow-moving cards, shared across the 3 seeded days (move on a weekly cadence) ----
function clockA_slow(overrides = {}) {
  return [
    {
      key: 'roi_coverage',
      title: 'AI ROI coverage',
      group: 'clockA',
      kind: 'metric',
      status: 'warn',
      headline: { value: '14%', label: 'of capex covered', sub: 'exogenous 9% · ~35% circular' },
      rows: [
        { label: 'Lab ARR', value: '$54B', delta: '+157%', state: 'good' },
        { label: 'vs capex', value: '$400B/yr', delta: '+60%' },
        { label: 'Exogenous', value: '9%', state: 'warn' },
        { label: 'Circular (NVDA→OpenAI→Azure)', value: '~35%', state: 'bad' },
      ],
      note: 'ARR outgrowing capex → Clock A closing on paper. Exogenous-vs-circular is the honesty check.',
    },
    {
      key: 'ai_demand',
      title: 'AI-infra demand',
      group: 'clockA',
      kind: 'metric',
      status: 'warn',
      headline: { value: '$0.30', label: 'cheapest frontier $/Mtok', sub: 'median $10.00' },
      rows: [
        { label: 'Cheapest frontier', value: '$0.30/Mtok' },
        { label: 'Median frontier', value: '$10.00/Mtok' },
        { label: 'Frontier-class models', value: '81' },
        { label: 'Total models', value: '338' },
      ],
      note: 'Price (the Jevons denominator) only. Falling = intelligence commoditizing; volume must outrun it.',
    },
    {
      key: 'consumer',
      title: 'Consumer (the demand base)',
      group: 'clockA',
      kind: 'metric',
      status: 'warn',
      headline: { value: '+3.2%', label: 'spend-over-income gap', sub: 'savings 2.6%' },
      rows: [
        { label: 'Real PCE YoY', value: '+2.1%' },
        { label: 'Real DPI YoY', value: '-1.1%', state: 'bad' },
        { label: 'Gap (spend − income)', value: '+3.2%', state: 'warn' },
        { label: 'Savings rate', value: '2.6%', state: 'warn' },
        { label: 'Revolving credit YoY', value: '+3.8%' },
        { label: 'CC delinquency', value: '2.92%', delta: '-0.14pp/yr' },
        { label: 'Debt service / DPI', value: '11.2%', delta: '+0.06pp/yr' },
        { label: 'Initial claims', value: '226k', delta: '+21k/qtr', state: 'warn' },
      ],
      note: 'Spend>income + low savings + rising debt-service = consumer-funded leg stretched.',
      ...overrides,
    },
    {
      key: 'distribution',
      title: 'Distribution (K-shape)',
      group: 'clockA',
      kind: 'metric',
      status: 'bad',
      headline: { value: '+2.2pp', label: 'productivity−pay wedge → capital', sub: 'labor share −2.9% YoY' },
      rows: [
        { label: 'Productivity YoY', value: '+2.8%', state: 'good' },
        { label: 'Real pay YoY', value: '+0.6%', state: 'bad' },
        { label: 'Wedge → capital', value: '+2.2pp', state: 'bad' },
        { label: 'Labor share (2017=100)', value: '95.0', delta: '-2.9% YoY', state: 'bad' },
        { label: 'Corp profits YoY', value: '+17.4%' },
      ],
      note: 'Gains to capital income-cap the demand base. The K-shape slows Clock A (ROI).',
    },
  ]
}

function backdrop_slow(memTape) {
  return [
    {
      key: 'buffett',
      title: 'Buffett indicator',
      group: 'backdrop',
      kind: 'metric',
      status: 'neutral',
      headline: { value: '218%', label: 'market cap / GDP', sub: 'richly valued' },
      rows: [{ label: 'Total mkt cap / GDP', value: '218%' }],
      note: 'Valuation backdrop — magnitude, not a trigger.',
    },
    {
      key: 'cross_asset',
      title: 'Cross-asset tape',
      group: 'backdrop',
      kind: 'metric',
      status: 'neutral',
      headline: { value: 'SKEW 142', label: 'tail-hedge demand', sub: 'pctile 24%' },
      rows: [
        { label: 'DXY', value: '101.39' },
        { label: 'Gold', value: '$4,158' },
        { label: 'BTC', value: '$62,263' },
        { label: 'Copper', value: '$6.16' },
      ],
      note: 'Macro cross-asset backdrop.',
    },
    {
      key: 'memory_prices',
      title: 'Memory super-cycle',
      group: 'backdrop',
      kind: 'metric',
      status: 'warn',
      headline: { value: '+40–50%', label: '3Q26 QoQ contract forecast', sub: 'vs consensus +15–20%' },
      rows: [
        { label: '3Q26 forecast', value: '+40–50% QoQ', state: 'good' },
        { label: 'Consensus', value: '+15–20% QoQ' },
        { label: 'Cycle-top marker', value: '~2028 ASP fall' },
        { label: 'Latest print', value: 'awaiting — MU 6/24', state: 'warn' },
      ],
      note: 'MU prints Wed 6/24 — first contract-price read vs the +40–50% super-bull call. The crux gauge.',
    },
    memTape,
  ]
}

// ---- per-day builder ----
function makeDay(d) {
  const stressStatus = d.stress >= 3 ? 'bad' : d.stress >= 2 ? 'warn' : 'warn' // label is misleading by design

  const regime = {
    key: 'regime',
    title: 'Macro regime',
    group: 'header',
    kind: 'stress',
    status: stressStatus,
    headline: { value: `${d.stress}/6`, label: 'stress signals', sub: `risk-on · ${d.style}` },
    extra: { stress: d.stress, available: 6 },
    rows: d.regimeSignals,
    note: 'Mechanical label can mislead while internals rot — read the signals, not the headline.',
  }

  const fearGreed = {
    key: 'fear_greed',
    title: 'Fear & Greed',
    group: 'header',
    kind: 'dial',
    status: 'neutral',
    headline: { value: String(Math.round(d.fng)), label: d.fngRating, sub: 'contrarian' },
    extra: { score: d.fng, rating: d.fngRating, subs: d.fngSubs },
    note: 'Contrarian — deep fear is constructive for buyers.',
  }

  const crypto_credit = {
    key: 'crypto_credit',
    title: 'Crypto / AI-infra credit',
    group: 'clockB',
    kind: 'metric',
    status: d.strc < 80 ? 'bad' : d.strc < 90 ? 'bad' : d.strc < 95 ? 'warn' : 'good',
    headline: { value: `$${d.strc.toFixed(1)}`, label: 'STRC (par 100)', sub: `${d.strcDisc}% vs par · ${d.strcBand}` },
    rows: [
      { label: 'STRC discount', value: `${d.strcDisc}%`, state: 'bad' },
      { label: 'Strategy prefs', value: `${d.prefsBelow}/4 below par`, delta: `${d.prefs5d}% 5d`, state: d.prefs5d < -3 ? 'bad' : 'warn' },
      { label: 'MSTR vs BTC (21d)', value: `${d.mstrBtc}%`, state: d.mstrBtc < -15 ? 'bad' : 'warn' },
      { label: 'BTC', value: `$${d.btc.toLocaleString()}` },
      { label: 'MSTR', value: `$${d.mstr}` },
    ],
    note: 'The leading credit edge. STRC<90 falling = de-risk; <80 = cut hard. Dress rehearsal for AI-infra credit.',
  }

  const hy_oas = {
    key: 'hy_oas',
    title: 'HY OAS (corporate backstop)',
    group: 'clockB',
    kind: 'metric',
    status: 'good',
    headline: { value: '2.65%', label: 'high-yield spread', sub: 'pctile 2% · tightening' },
    rows: [
      { label: '1m change', value: '-0.09pp', state: 'good' },
      { label: '252d percentile', value: '2%' },
      { label: 'State', value: 'tightening', state: 'good' },
    ],
    note: 'The lone backstop still green — corporate credit has not confirmed. Crack confined to the crypto edge.',
  }

  const momentum = {
    key: 'momentum',
    title: 'Momentum / crowding',
    group: 'magnitude',
    kind: 'legs',
    status: d.legsBasing >= 4 ? 'warn' : 'bad',
    headline: { value: `${d.legsBasing}/6`, label: 'legs basing (5d ≥ 0)', sub: `avg ${d.legsAvgOffhi}% off-hi` },
    extra: { vix: d.vix, vvix: d.vvix, legs: d.legs },
    note: 'off-hi = unwind so far · run63 = fuel left · 5d ≥ 0 = basing. Dip-buy needs legs basing.',
  }

  const cta = {
    key: 'cta',
    title: 'CTA systematic flows',
    group: 'magnitude',
    kind: 'cta',
    status: d.ctaShort <= 0 ? 'bad' : d.ctaShort < 2 ? 'warn' : 'good',
    headline: { value: `+${d.ctaShort}%`, label: 'to short trigger', sub: `SPX ${d.ctaSpot.toLocaleString()}` },
    extra: { spot: d.ctaSpot, levels: d.ctaLevels },
    note: 'Breach = systematic supply ON. Supply into calm credit is the entry phase. Levels asof 2026-06-09.',
  }

  const spx_breadth = {
    key: 'spx_breadth',
    title: 'SPX breadth',
    group: 'magnitude',
    kind: 'breadth',
    status: d.spx50 >= 60 ? 'good' : d.spx50 >= 50 ? 'warn' : 'bad',
    headline: { value: `${d.spx50}%`, label: '> 50dma', sub: 'n=502' },
    extra: { pct50: d.spx50, pct200: d.spx200 },
    note: 'The load-bearing breadth measure (n≈500).',
  }

  const retail_froth = {
    key: 'retail_froth',
    title: 'Retail froth (payload size)',
    group: 'magnitude',
    kind: 'metric',
    status: 'bad',
    headline: { value: '+30.5%', label: 'margin debt YoY', sub: '$622B' },
    rows: [
      { label: 'Margin debt', value: '$622B', delta: '+30.5% YoY', state: 'bad' },
      { label: 'High-beta SPHB/SPLV', value: '-4.8% off-hi', delta: '-2.1% 5d', state: 'warn' },
      { label: '2x-ETF casino off-hi', value: `${d.casinoOffhi}%`, state: 'bad' },
      { label: '2x-ETF casino 5d', value: `${d.casino5d}%`, state: 'bad' },
    ],
    note: 'The payload size, not the fuse — froth amplifies the move; credit + ROI trigger the break.',
  }

  const mag7 = {
    key: 'mag7',
    title: 'Mag7 concentration',
    group: 'magnitude',
    kind: 'metric',
    status: 'neutral',
    headline: { value: `${d.mag7Above}/7`, label: 'above 50dma', sub: 'color only — not breadth' },
    rows: d.mag7Names.map(m => ({
      label: m.t,
      value: m.last,
      delta: `${m.d1 >= 0 ? '+' : ''}${m.d1}%`,
      state: m.above ? 'good' : 'bad',
    })),
    note: 'n=7 is not breadth — the breadth measure is the SPX panel.',
  }

  const groups = {
    header: [regime, fearGreed],
    clockA: clockA_slow(),
    clockB: [crypto_credit, hy_oas],
    magnitude: [momentum, cta, spx_breadth, retail_froth, mag7],
    backdrop: backdrop_slow(d.memTape),
  }

  return {
    date: d.date,
    regimeLabel: 'risk-on',
    style: d.style,
    posture: d.posture,
    synopsis: d.synopsis,
    what_changed: d.whatChanged,
    groups,
  }
}

// ---------- 2026-06-23 (full real transcription) ----------
const day23 = makeDay({
  date: '2026-06-23',
  style: 'convexity favored',
  stress: 0,
  vix: 19.8,
  vvix: 100.9,
  fng: 28,
  fngRating: 'fear',
  fngSubs: [
    ['Momentum', 'fear'],
    ['Strength', 'fear'],
    ['Breadth', 'extreme fear'],
    ['Put/Call', 'fear'],
    ['Volatility', 'neutral'],
    ['Safe-haven', 'extreme fear'],
    ['Junk-bond', 'extreme fear'],
  ],
  regimeSignals: [
    { label: 'Credit (HY OAS)', value: '2.65%', delta: 'pctile 2%', state: 'good' },
    { label: 'Rate vol (MOVE)', value: '65', delta: 'pctile 16%', state: 'good' },
    { label: 'Equity vol (VIX TS)', value: '19.8 / 21.2', delta: 'contango', state: 'good' },
    { label: 'Fin. conditions (NFCI)', value: '-0.51', delta: 'looser', state: 'good' },
    { label: 'Real rate (10y TIPS)', value: '2.21%', delta: '+0.03pp/1m', state: 'good' },
    { label: 'Breadth (RSP/SPY)', value: '-1.8% 50d', delta: 'narrowing', state: 'good' },
  ],
  spx50: 60,
  spx200: 62,
  strc: 87.68,
  strcDisc: -12.3,
  strcBand: 'peg failing',
  prefsBelow: 4,
  prefs5d: -7.6,
  mstrBtc: -29,
  btc: 62274,
  mstr: 106.15,
  legsBasing: 2,
  legsAvgOffhi: -6.1,
  legs: [
    { label: 'Momentum factor', pair: 'MTUM/SPY', offhi: -3.1, run63: 35.5, d5: 1.4 },
    { label: 'Mag7 mega-cap', pair: 'MAGS/SPY', offhi: -9.5, run63: 7.0, d5: -2.6 },
    { label: 'Semis', pair: 'SMH/SPY', offhi: -5.3, run63: 60.0, d5: -1.0 },
    { label: 'High-beta/low-vol', pair: 'SPHB/SPLV', offhi: -4.8, run63: 28.5, d5: -2.1 },
    { label: 'Breadth (eq/cap)', pair: 'RSP/SPY', offhi: -4.4, run63: 9.5, d5: 0.9 },
    { label: 'Growth/value', pair: 'VUG/VTV', offhi: -9.2, run63: 13.7, d5: -3.4 },
  ],
  ctaShort: 1.0,
  ctaSpot: 7388,
  ctaLevels: [
    { name: 'short', level: 7312, dist: 1.0 },
    { name: 'medium', level: 7017, dist: 5.3 },
    { name: 'long', level: 6611, dist: 11.8 },
  ],
  casinoOffhi: -43.9,
  casino5d: -19.9,
  mag7Above: 1,
  mag7Names: [
    { t: 'AAPL', last: '297.98', d1: 0.3, above: true },
    { t: 'MSFT', last: '373.14', d1: 1.6, above: false },
    { t: 'GOOGL', last: '346.60', d1: -0.9, above: false },
    { t: 'AMZN', last: '234.40', d1: 0.7, above: false },
    { t: 'NVDA', last: '202.07', d1: -3.2, above: false },
    { t: 'META', last: '563.91', d1: 0.0, above: false },
    { t: 'TSLA', last: '383.30', d1: -5.4, above: false },
  ],
  memTape: {
    key: 'memory_tape',
    title: 'Memory tape (live proxy)',
    group: 'backdrop',
    kind: 'metric',
    status: 'bad',
    headline: { value: 'EWY 196.9', label: 'Samsung / SK Hynix proxy', sub: '-10.1% 1d' },
    rows: [
      { label: 'EWY', value: '196.89' },
      { label: '1d', value: '-10.1%', state: 'bad' },
      { label: '5d', value: '-6.9%', state: 'bad' },
      { label: 'Off 63d high', value: '-10.2%', state: 'bad' },
    ],
    note: 'Live memory-duopoly proxy — leads the contract print + Asia risk. Broke hard today.',
  },
  posture: {
    window: 'SHUT',
    gates: [
      { label: 'Legs basing', state: 'bad', detail: '2/6 basing' },
      { label: 'VIX settling', state: 'bad', detail: '19.8 rising · VVIX 100.9' },
      { label: 'Credit calm', state: 'bad', detail: 'STRC peg failing' },
    ],
    triggers: [
      { label: 'STRC < 90', active: true, detail: '$87.7 — de-risk' },
      { label: 'STRC < 80', active: false, detail: 'cut hard' },
      { label: 'VIX > 22', active: false, detail: 'at 19.8' },
      { label: 'CTA breach', active: false, detail: '+1.0% away' },
      { label: 'VVIX > 100', active: true, detail: '100.9' },
    ],
  },
  whatChanged: [
    'VIX 17 → 20',
    'SPX breadth 56% → 60%',
    'F&G 35 → 28',
    'STRC 88.8 → 87.7',
    'Mag7 2 → 1',
    'legs basing 4 → 2',
  ],
  synopsis:
    'Yesterday\'s K-shape rotation broke today. The "suppliers over buyers" trade that held the tape up — memory and semis ripping while the Mag7 rolled — reversed hard: SMH −6.5%, MU −10.6%, EWY −10.1% (the Samsung/SK Hynix proxy), SOXX −7.3%, and the whole power-semi complex red. The last leg standing rolled over, and the only green was a flight to quality within tech — MSFT, AMZN, AAPL bid while the levered/cyclical edge got sold. This is no longer rotation within the AI complex; it\'s the complex itself starting to de-gross.\n\n'
    + 'All three dip-buy gates are red — and worse than Monday. Credit edge deteriorating: STRC $87.7 (from $88.8), the pref stack −7.6%/5d, MSTR −29% vs BTC (funding window closing). Vol rising into stress: VIX 19.8, VVIX 100.9 — vol-of-vol crossed the >100 line. Legs breaking: only 2/6 basing. The window\'s rule is legs basing AND VIX settling AND credit calm — every one points the wrong way. The lone backstop still green is HY OAS 2.65%; corporate credit hasn\'t confirmed, so the crack stays confined to the crypto-credit edge. Don\'t trust the mechanical "risk-on 0/6" label — the internals (F&G 28, Mag7 1/7, CTA only +1.0% from the systematic-supply trigger) are the read.\n\n'
    + 'The live crux is memory — and it reports tomorrow. MU prints Wednesday (6/24), the first contract-price read against the +40–50% QoQ super-bull call. The tape front-ran it today — MU −10.6%, EWY −10.1% into the print. Prints > consensus = super-cycle intact; < consensus = the top pulls forward.\n\n'
    + 'Net: magnitude is screaming (positioning extreme, froth maxed, the supplier leg broke) while the trigger is stirring but unconfirmed (STRC cracking, VVIX>100, claims ticking — but HY OAS calm, VIX only 20). Posture: stay patient, keep dry powder, no shorts into an extended-but-untimed top; wait for capitulation (STRC<80, or a VIX>22 spike-then-base plus a CTA breach) for the back-up-the-truck.',
})

// ---------- 2026-06-22 (real dynamic values; slow cards reused) ----------
const day22 = makeDay({
  date: '2026-06-22',
  style: 'convexity favored',
  stress: 1,
  vix: 17.28,
  vvix: 92,
  fng: 34.7,
  fngRating: 'fear',
  fngSubs: day23.groups.header[1].extra.subs,
  regimeSignals: day23.groups.header[0].rows.map(r => ({ ...r })),
  spx50: 55.6,
  spx200: 60,
  strc: 88.79,
  strcDisc: -11.2,
  strcBand: 'peg failing',
  prefsBelow: 4,
  prefs5d: -4.1,
  mstrBtc: -19,
  btc: 63100,
  mstr: 109.4,
  legsBasing: 4,
  legsAvgOffhi: -3.9,
  legs: [
    { label: 'Momentum factor', pair: 'MTUM/SPY', offhi: -2.0, run63: 36.0, d5: 0.6 },
    { label: 'Mag7 mega-cap', pair: 'MAGS/SPY', offhi: -7.8, run63: 8.5, d5: -1.2 },
    { label: 'Semis', pair: 'SMH/SPY', offhi: -1.1, run63: 64.0, d5: 2.3 },
    { label: 'High-beta/low-vol', pair: 'SPHB/SPLV', offhi: -3.0, run63: 30.0, d5: 0.4 },
    { label: 'Breadth (eq/cap)', pair: 'RSP/SPY', offhi: -3.6, run63: 10.0, d5: 0.2 },
    { label: 'Growth/value', pair: 'VUG/VTV', offhi: -6.9, run63: 15.0, d5: -1.1 },
  ],
  ctaShort: 1.6,
  ctaSpot: 7421,
  ctaLevels: [
    { name: 'short', level: 7312, dist: 1.6 },
    { name: 'medium', level: 7017, dist: 5.8 },
    { name: 'long', level: 6611, dist: 12.3 },
  ],
  casinoOffhi: -34.0,
  casino5d: -8.0,
  mag7Above: 2,
  mag7Names: [
    { t: 'AAPL', last: '297.10', d1: 0.5, above: true },
    { t: 'MSFT', last: '367.20', d1: -0.4, above: true },
    { t: 'GOOGL', last: '349.70', d1: -1.0, above: false },
    { t: 'AMZN', last: '232.80', d1: -0.6, above: false },
    { t: 'NVDA', last: '208.80', d1: 1.3, above: false },
    { t: 'META', last: '563.90', d1: 0.4, above: false },
    { t: 'TSLA', last: '405.20', d1: -1.0, above: false },
  ],
  memTape: {
    key: 'memory_tape',
    title: 'Memory tape (live proxy)',
    group: 'backdrop',
    kind: 'metric',
    status: 'good',
    headline: { value: 'EWY 219.0', label: 'Samsung / SK Hynix proxy', sub: '+1.8% 1d' },
    rows: [
      { label: 'EWY', value: '219.00' },
      { label: '1d', value: '+1.8%', state: 'good' },
      { label: '5d', value: '+4.0%', state: 'good' },
      { label: 'Off 63d high', value: '-0.3%', state: 'good' },
    ],
    note: 'Live memory-duopoly proxy — at highs into the MU print. (Approximated for pagination.)',
  },
  posture: {
    window: 'SHUT',
    gates: [
      { label: 'Legs basing', state: 'good', detail: '4/6 basing' },
      { label: 'VIX settling', state: 'good', detail: '17.3 contango' },
      { label: 'Credit calm', state: 'bad', detail: 'STRC peg failing' },
    ],
    triggers: [
      { label: 'STRC < 90', active: true, detail: '$88.8 — de-risk' },
      { label: 'STRC < 80', active: false, detail: 'cut hard' },
      { label: 'VIX > 22', active: false, detail: 'at 17.3' },
      { label: 'CTA breach', active: false, detail: '+1.6% away' },
      { label: 'VVIX > 100', active: false, detail: '92' },
    ],
  },
  whatChanged: ['VIX 16 → 17', 'F&G 37 → 35', 'STRC 88.6 → 88.8', 'Mag7 3 → 2'],
  synopsis:
    'The K-shape rotation still holding: suppliers (memory, semis) bid while the Mag7 grinds lower. Credit edge the standout worry — STRC $88.8, still peg-failing, the pref stack soft. Two gates green (legs basing 4/6, VIX 17 in contango) but credit keeps the dip-buy window shut. Magnitude maxed, trigger not confirmed. All eyes on the MU print Wednesday. (Slow-moving cards reused from 06-23; dynamic values are this day\'s.)',
})

// ---------- 2026-06-21 (real dynamic values; slow cards reused) ----------
const day21 = makeDay({
  date: '2026-06-21',
  style: 'convexity favored',
  stress: 1,
  vix: 16.4,
  vvix: 88,
  fng: 37.3,
  fngRating: 'fear',
  fngSubs: day23.groups.header[1].extra.subs,
  regimeSignals: day23.groups.header[0].rows.map(r => ({ ...r })),
  spx50: 56.2,
  spx200: 61,
  strc: 88.59,
  strcDisc: -11.4,
  strcBand: 'peg failing',
  prefsBelow: 4,
  prefs5d: -3.2,
  mstrBtc: -16,
  btc: 63500,
  mstr: 111.0,
  legsBasing: 4,
  legsAvgOffhi: -3.4,
  legs: [
    { label: 'Momentum factor', pair: 'MTUM/SPY', offhi: -1.5, run63: 37.0, d5: 1.0 },
    { label: 'Mag7 mega-cap', pair: 'MAGS/SPY', offhi: -7.0, run63: 9.0, d5: -0.5 },
    { label: 'Semis', pair: 'SMH/SPY', offhi: -0.6, run63: 65.0, d5: 3.1 },
    { label: 'High-beta/low-vol', pair: 'SPHB/SPLV', offhi: -2.4, run63: 31.0, d5: 0.8 },
    { label: 'Breadth (eq/cap)', pair: 'RSP/SPY', offhi: -3.2, run63: 10.5, d5: 0.5 },
    { label: 'Growth/value', pair: 'VUG/VTV', offhi: -6.2, run63: 16.0, d5: -0.4 },
  ],
  ctaShort: 2.1,
  ctaSpot: 7460,
  ctaLevels: [
    { name: 'short', level: 7312, dist: 2.1 },
    { name: 'medium', level: 7017, dist: 6.3 },
    { name: 'long', level: 6611, dist: 12.8 },
  ],
  casinoOffhi: -30.0,
  casino5d: -5.0,
  mag7Above: 3,
  mag7Names: [
    { t: 'AAPL', last: '296.10', d1: 0.2, above: true },
    { t: 'MSFT', last: '368.70', d1: 0.3, above: true },
    { t: 'GOOGL', last: '353.20', d1: 0.1, above: true },
    { t: 'AMZN', last: '234.20', d1: -0.2, above: false },
    { t: 'NVDA', last: '206.10', d1: -0.4, above: false },
    { t: 'META', last: '561.60', d1: 0.2, above: false },
    { t: 'TSLA', last: '409.30', d1: 0.6, above: false },
  ],
  memTape: {
    key: 'memory_tape',
    title: 'Memory tape (live proxy)',
    group: 'backdrop',
    kind: 'metric',
    status: 'good',
    headline: { value: 'EWY 215.1', label: 'Samsung / SK Hynix proxy', sub: '+0.9% 1d' },
    rows: [
      { label: 'EWY', value: '215.10' },
      { label: '1d', value: '+0.9%', state: 'good' },
      { label: '5d', value: '+3.2%', state: 'good' },
      { label: 'Off 63d high', value: '-1.1%', state: 'good' },
    ],
    note: 'Live memory-duopoly proxy — grinding higher. (Approximated for pagination.)',
  },
  posture: {
    window: 'SHUT',
    gates: [
      { label: 'Legs basing', state: 'good', detail: '4/6 basing' },
      { label: 'VIX settling', state: 'good', detail: '16.4 contango' },
      { label: 'Credit calm', state: 'bad', detail: 'STRC peg failing' },
    ],
    triggers: [
      { label: 'STRC < 90', active: true, detail: '$88.6 — de-risk' },
      { label: 'STRC < 80', active: false, detail: 'cut hard' },
      { label: 'VIX > 22', active: false, detail: 'at 16.4' },
      { label: 'CTA breach', active: false, detail: '+2.1% away' },
      { label: 'VVIX > 100', active: false, detail: '88' },
    ],
  },
  whatChanged: ['VIX 16 → 16', 'F&G 39 → 37', 'STRC 89.0 → 88.6'],
  synopsis:
    'Tape calm on the surface — VIX 16, breadth steady, suppliers leading. The one persistent tell is the crypto-credit edge: STRC stuck below par at $88.6, peg-failing, the leading indicator for AI-infra leverage. Dip-buy window shut on credit alone. Froth and positioning remain the payload; nothing has lit the fuse yet. (Slow-moving cards reused from 06-23; dynamic values are this day\'s.)',
})

// ---------- write ----------
const db = new DatabaseSync(DB_PATH)
db.exec('DROP TABLE IF EXISTS briefs')
db.exec('CREATE TABLE briefs (date TEXT PRIMARY KEY, payload TEXT NOT NULL)')
const ins = db.prepare('INSERT INTO briefs (date, payload) VALUES (?, ?)')
for (const day of [day21, day22, day23]) {
  ins.run(day.date, JSON.stringify(day))
}
console.log(`seeded ${DB_PATH} with: ${[day21, day22, day23].map(d => d.date).join(', ')}`)
db.close()
