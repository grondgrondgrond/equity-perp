# Methodology — perp funding-rate harvesting study

**Status: LOCKED** (v2, 2026-07-24). Owner: Derek. Changes require Derek's explicit
sign-off and an entry in the decision log below — do not silently amend, extend, or
"improve" any step. Implementation is canonical in code; this document describes it
and records why.

## Pipeline overview

```
step 1  scripts/universe.py                 -> data/processed/universe_v2.parquet
step 2  scripts/collect_prices.py universe
        scripts/load_market_data.py         -> data/processed/market_panel_v2.parquet
                                               data/processed/market_panel_qc.parquet
step 3+ studies (backtests, forecasts, dashboards) consume market_panel_v2.parquet
        and universe_v2.parquet — never raw files, never re-implemented screens.
```

## Step 1 — Universe selection (v2)

Canonical: `scripts/universe.py::select_universe()`.

1. **Venues:** Hyperliquid main, HL xyz (HIP-3), Lighter — the venues that passed the
   legitimacy review (`report/notes/venue-legitimacy-2026-07.md`). Excluded: Aster,
   Extended, Helix, edgeX, Paradex (farm-inflated/dead), Ostium (exploited 2026-07-15),
   Drift (offline), Jupiter/GMX (no harvestable funding leg). dYdX is out of universe
   (thin) but retained as a data source for cross-venue funding comparisons.
2. **History:** ≥ 21 days of funding data.
3. **Memecoins excluded** — curated set `scripts/build_expansion.py::MEMES`.
4. **Crypto whitelist:** BTC, ETH, SOL on any venue; HYPE on Hyperliquid only; LIT on
   Lighter only. All other crypto excluded — including XMR (explicit decision).
5. **Liquidity:** 24h volume ≥ $1M AND open interest > $1M, evaluated on the live
   snapshot at selection time. Snapshot-dependent: rerun after every data refresh;
   depth-cut names (e.g. SOXL/SAMSUNG/QQQ/TSLA on Lighter) re-enter if books grow.
6. **No funding-rate cutoff.** Negative-carry names remain in as long-perp candidates.

Result at 2026-07-24: **81 markets** (63 xyz / 14 Lighter / 4 HL main; 59 RWA equity,
12 commodity-metal, 8 whitelisted crypto, 2 FX/other).
Audit dashboard: https://claude.ai/code/artifact/7830aeb3-175b-45fd-b330-876f9a23278b

## Step 2 — Market data layer

Canonical: `scripts/load_market_data.py` (inputs collected by
`scripts/collect_prices.py universe`).

Per in-universe market, on a common hourly UTC grid spanning the union of both series:

| column | definition |
|---|---|
| `funding_rate_1h` | decimal per hour, **positive = longs pay shorts**; interval venues normalized (rate ÷ interval hours); HL ms-offset timestamps floored to the hour |
| `close` | venue trade-candle close — the observable **mark proxy** for liquidation modeling (HL liquidations actually use an oracle-blended mark; known, documented approximation) |
| `ret_1h` | simple close-to-close return |

Locked conventions:
- **No imputation in the canonical layer.** Gaps are NaN; each downstream study
  decides (and documents) its own fill policy.
- Lookback: min(200d, venue history). Lighter funding history is bounded ~90d.
- QC is part of the layer: `market_panel_qc.parquet` records coverage, overlap,
  and largest price gap per market. Studies should exclude/flag markets failing
  their own window requirements (young listings at 2026-07-24: xyz AMAT/BOT/KIOXIA
  with <30d overlap; one 96h price gap on Lighter).

## Step 3 — Funding-rate forecast evaluation

Canonical: `scripts/forecast_funding.py` → `data/processed/funding_forecast_eval.parquet`.

Three model classes (Derek's spec), forecasting mean funding over the next 7d and 30d:
1. **SMA(W)** — trailing W-day mean, extrapolated flat. W ∈ {3,7,14,30,60}.
2. **EWMA(h)** — halflife-h EWMA, extrapolated flat. h ∈ {1,3,7,14,30,60}.
3. **DECAY(hs, κ, A)** — starts at EWMA(hs), decays with timescale κ toward anchor A
   (zero or long EWMA); forecast = horizon average of the path:
   `pred(H) = A + (E_hs − A)·(κ/H)(1 − e^(−H/κ))`.
   hs ∈ {1,3,7}, κ ∈ {3,7,14,30,60}, A ∈ {zero, ewma30, ewma60}.

Locked protocol: in-universe markets from `market_panel_v2` only; daily 00:00 UTC
origins; ≥60d history since first observation; ≥90% hour coverage on feature and
target windows; targets annualized (×8760); error = RMSE, aggregated across markets
by median nRMSE (RMSE ÷ per-market target std); baselines = zero and persistence
(SMA with W = horizon). Markets too short for a horizon drop out automatically.
**Champion selection is an output, re-derived on each refresh — not part of the lock.**

Result at 2026-07-24 (59 markets @1w, 42 @1m): DECAY(hs=3, κ=3, A=ewma60) tops the
leaderboard at both horizons (nRMSE 1.094 @1w, 1.448 @1m), but paired per-market
comparison shows flat EWMA(60) beats it on 74% of markets @1m — the top cluster is
statistically indistinguishable. Robust findings: fast trackers and zero-anchor
decay reliably worse → funding reverts to its own long-run level, not to zero, and
week-scale funding momentum is mostly noise.

**OPERATIVE MODEL (revised 2026-07-25, Derek): flat EWMA on ALL venues.**
Canonical implementation: `scripts/forecast_funding.py::operative_forecast()`.
EWMA(30) for the 1-week horizon, EWMA(60) for the 1-month horizon. On young
markets the adjusted EWMA approximates the expanding mean — intended behavior,
no special young-market handling needed.

History of the Lighter exception (2026-07-24, retired 2026-07-25): a zero-anchor
decay model (`0.23·EWMA(3d)` at 1m) was briefly operative for Lighter, supported
by a 1-week-only evaluation on ~22 tail origins — Lighter's 89d history never
allowed a 1-month test. Visual diagnostics plus a relaxed-gate 1m head-to-head
showed it structurally under-forecast Lighter equity carry (median bias −7pp;
SKHYNIX −76pp: realized forward funding ran +80–150% all sample while the model
predicted +10–40%). Retired. Directional evidence, not a precise measurement —
~2 independent 30d windows per market in one regime. Open items: (a) extend
Lighter funding history to listing and re-run the locked step-3 evaluation with
genuine 1m targets; (b) Lighter commodity perps (WTI/BRENTOIL) DID show genuine
funding collapse where decay was better — assess a commodity carve-out then.

## Standing analytical conventions

- All timestamps UTC. Annualization of funding: mean hourly rate × 8760 (linear).
- Units verified per venue: Lighter `/fundings` rate is **percent per hour**
  (cross-checked vs HL same-hour); Lighter candles at `/api/v1/candles`
  (not `/candlesticks`); Yahoo US hourly bars sit on :30 — floor to hour;
  KRX dividends are KRW — convert at ex-date FX; DeFiLlama API paywalled —
  venue-level volume comes from venue APIs directly; SOFR from NY Fed API.
- Every study writeup must state: cost model, denominator definition (notional vs
  committed capital vs NAV), window/recency effects, and any deviation from the
  panel's no-imputation default.

## Decision log

| date | decision | owner |
|---|---|---|
| 2026-07-24 | Universe v1 (vol ≥ $3M, funding > 0, ad-hoc judgment) — superseded same day after selection audit exposed unflagged judgment calls | Claude (unconsulted — the trigger for the consult-first process rule) |
| 2026-07-24 | Universe v2 locked: vol ≥ $1M AND OI > $1M, no funding cutoff, memecoins out, crypto whitelist BTC/ETH/SOL + HYPE(HL) + LIT(Lighter); XMR deliberately excluded | Derek |
| 2026-07-24 | Step 2 locked: hourly panel, candle-close mark proxy, simple returns, no imputation, QC file mandatory | Derek (spec), Claude (conventions, stated & accepted) |
| 2026-07-24 | Step 3 locked: forecast evaluation — 3 model classes (SMA/EWMA/decay-from-short-EWMA), 7d & 30d horizons, squared error, median nRMSE aggregation, zero+persistence baselines; champion = output not lock | Derek (models, horizons, metric), Claude (protocol details, stated) |
| 2026-07-24 | Operative funding forecast = flat EWMA(30) + EWMA(60), decay champion shelved (indistinguishable in paired comparison; simplicity preferred) | Derek |
| 2026-07-24 | Operative model split by platform: HL/xyz keep flat EWMA(30/60); Lighter gets zero-anchor decay from EWMA(3), κ=7 (long EWMAs measured near-worst on Lighter; post-TGE funding decline). 1m on Lighter = unvalidated extrapolation | Derek (split), Claude (Lighter parameterization from subgroup leaderboard, stated) |
| 2026-07-25 | Lighter decay model RETIRED after visual diagnostics exposed structural 1m under-forecast (the supporting eval was 1w-only on ~22 tail origins). Operative model unified: flat EWMA(30/60) everywhere. Pending: Lighter history extension + proper 1m re-eval; possible commodity carve-out | Derek (sign-off), Claude (diagnostics) |
