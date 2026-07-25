# equity-perp — working agreements

RWA/crypto perp funding-rate harvesting research for a sub-$1M build-out. Layout,
conventions, and study history: see README.md.

## Methodology is LOCKED — read METHODOLOGY.md first

`METHODOLOGY.md` is the locked spec (universe rule v2, market-data layer,
conventions, decision log). Do not amend, extend, or deviate from it without
Derek's explicit sign-off + a decision-log entry. Operationally:
- Universe: consume `data/processed/universe_v2.parquet` (from
  `scripts/universe.py`); never hand-pick assets or re-implement screens.
  Rerun after data refresh — vol/OI screens are snapshot-dependent.
- Market data: consume `data/processed/market_panel_v2.parquet` (from
  `scripts/collect_prices.py universe` + `scripts/load_market_data.py`);
  gaps are NaN by design — each study documents its own fill policy.
- Studies never read raw files directly.
- Step 3 (locked; revised 2026-07-25): `scripts/forecast_funding.py` = the
  funding-forecast evaluation. **Operative expected-carry model = flat EWMA on
  ALL venues** via `forecast_funding.operative_forecast()`: EWMA(30) @1w,
  EWMA(60) @1m. The 2026-07-24 Lighter decay model is RETIRED (structurally
  under-forecast; see METHODOLOGY decision log) — do not resurrect it without
  the Lighter history extension + a genuine 1m eval. Never use raw trailing
  7d funding as a carry input.

## Process rules (Derek's standing instructions)

- **Consult before deciding.** Design decisions — screens, thresholds, model
  parameters, risk policies, scope — are Derek's. Propose options with
  trade-offs and ask; don't bake in defaults and present results. When a
  parameter is cheap to sweep, sweep it and show sensitivity instead of picking.
- **Make every assumption explicit** in any backtest/analysis writeup: cost
  models, units, alignment conventions, denominator definitions (notional vs
  committed capital vs NAV), annualization, window/recency effects.
- Data gotchas already learned (don't rediscover): HL funding timestamps carry
  ms offsets — floor to hour before joining; Yahoo US hourly bars sit on :30;
  KRX dividends are KRW — convert at ex-date FX; Lighter candles live at
  `/api/v1/candles` (not /candlesticks); Lighter funding `rate` is percent/hour;
  DeFiLlama API is paywalled (402); use NY Fed API for SOFR, not FRED CSV.
- Python: `.venv/bin/python`. All timestamps UTC. Funding normalized to hourly
  decimal rates, positive = longs pay shorts (`expansion_funding_panel.parquet`).
