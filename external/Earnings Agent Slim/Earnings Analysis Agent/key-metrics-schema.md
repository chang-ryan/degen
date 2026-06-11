# key_metrics.yaml — Format Specification

## Purpose
Per-ticker configuration file that tells the agent which metrics to track, how to find them in the consensus CSV, and how to parse company/sector-specific KPIs.

## File Location
`workspace/{TICKER}/key_metrics.yaml`

## Schema
```yaml
ticker: XYZ
sector: semiconductors

universal_metrics:
  - name: revenue
    skip: false              # set true to skip this metric for this ticker
  - name: gross_margin
    skip: false
  - name: ebitda
    skip: false              # set true for pre-revenue or early-stage companies
  - name: fcf
    skip: false
  - name: eps
    skip: false              # set true for pre-earnings companies

industry_kpis:
  - name: segment1_revenue
    type: segment_revenue
    unit: millions
    consensus_field: "SEGMENT1_SALES"  # field name as it appears in your consensus CSV
  - name: segment2_revenue
    type: segment_revenue
    unit: millions
    consensus_field: "SEGMENT2_SALES"
  - name: gross_margin_pct
    type: adjusted_margin
    unit: percent
    consensus_field: "GROSS_MARGIN"

# Column mapping for consensus.csv
# Update these if your CSV uses different column headers
column_mapping:
  ticker: "Ticker"
  metric: "Metric"
  period: "Period"
  mean: "Mean"
  high: "High"
  low: "Low"
  n_estimates: "N_Estimates"
  as_of_date: "As_Of_Date"

transcript_quarters: 8      # override default; min 4; max 12
guidance_quarters: 6        # how far back to pull guidance history
```

## Auto-Generation (Bootstrap)
On first run for a new ticker, if `key_metrics.yaml` does not exist, the agent auto-generates it:
1. Read `consensus.csv` headers
2. Detect column mapping by matching common column name patterns
3. Extract unique values from the `Metric` column
4. Map field names to `universal_metrics` and `industry_kpis`:
   - `SALES` → revenue
   - `EPS` → eps
   - `EBITDA` → ebitda
   - `GROSS_MARGIN` → gross_margin
   - `OPER_CASH_FLOW` or `FCF` → fcf
   - All other fields → `industry_kpis` with `consensus_field` set to the original field name
5. Set `skip: false` for all universal metrics found in CSV; set `skip: true` for any not present
6. Set `transcript_quarters: 8` and `guidance_quarters: 6` as defaults
7. **HALT and display** — user must review and confirm before analysis proceeds

## Field Definitions

### `universal_metrics`
Always track these regardless of sector. Corresponds to the consensus field names in your CSV.

### `industry_kpis`
Company/sector-specific metrics. These drive the sector-specific comparison logic. Examples by sector:
- **Healthcare devices**: system_placements, procedure_volumes, recurring_revenue_pct
- **SaaS/Software**: NRR, ARR, churn_rate, seats, ARPU
- **Retail**: SSS, ASP, transaction_volume, store_count
- **Industrials**: organic_growth, backlog, book_to_bill, pricing_realization

### `consensus_field` (industry_kpis only)
Maps this KPI to the corresponding field name in the consensus CSV. Used to look up consensus data for industry-specific metrics. If the `consensus_field` value is not found in the CSV's `Metric` column, the agent **WARNs** ("consensus data not available for {name} — expected field '{consensus_field}' not found in CSV") and skips consensus comparison for that KPI. The KPI will still appear in the output but with "N/A — no consensus data" in the consensus columns.

### `skip` flag (universal_metrics)
Set `skip: true` for any universal metric that is not meaningful for this ticker. The agent will:
- Omit it from the Expectations Stack
- Omit it from the Line-Item Scorecard
- Not penalize the ticker for missing data on skipped metrics

Use cases: pre-revenue medtech (skip EPS, EBITDA), early-stage biotech (skip FCF, EBITDA), financials (may skip EBITDA in favor of industry KPIs like NII).

### `type` field options
- `segment_revenue` — a segment line within total revenue
- `adjusted_margin` — margin figure (pct)
- `volume_metric` — unit volume (placements, procedures, transactions)
- `rate_metric` — a rate (churn %, NRR %, attach rate)
- `absolute_metric` — an absolute dollar figure that's not revenue

### `transcript_quarters`
Default is 8 (fixed). Override per ticker if needed (e.g., company went public recently). Minimum 4 quarters required for language comparison.

### `guidance_quarters`
Default 6 quarters of guidance history. Used for guidance track record analysis in pre-earnings (Appendix B).

## Consensus CSV Expected Format
The agent expects a CSV with columns defined in `column_mapping` above. Default:
```
Ticker | Metric | Period | Mean | High | Low | N_Estimates | As_Of_Date
```

Column resolution is done through `column_mapping` — if your CSV uses different headers, update the mapping. The agent will **HALT** if it cannot resolve all required columns.

Validation rules:
1. All columns in `column_mapping` must resolve to actual CSV headers — **HALT** if missing
2. `as_of_date` must not be more than 7 days before earnings date — **WARN** if stale
3. `n_estimates` < 3 for any key metric — **WARN** as thin coverage
4. If a metric listed in `universal_metrics` (with `skip: false`) or `industry_kpis` has no matching row in the CSV, **WARN** and mark that metric as "no consensus data available" in output
