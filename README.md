# equity-perp — RWA perps market scoping

Research project scoping whether the RWA/equity perpetuals space is worth a trading build-out.

## Layout

```
data/raw/          # per-source parquets, written by scripts/collect_*.py
  hyperliquid/     # HIP-3 builder dexes (xyz, vntl, km, cash, ...): asset snapshots,
                   # hourly funding history, daily/hourly candles, OI caps
  ostium/          # Ostium (Arbitrum RWA perps): pairs, funding/rollover history, volumes
  longtail/        # gTrade (gains_*), Avantis (avantis_*), Aster (aster_*), Vest (vest_*),
                   # Paradex/Helix/extended probes
  kraken/          # Kraken xStocks tokenized-equity spot (basis reference)
  defillama/       # platform-level daily volume trajectories (API paywalled since ~Jul 2026)
  dydx/            # dYdX v4 indexer: markets + 90d hourly funding (2026-07-24 expansion)
  lighter/         # Lighter zk-CLOB: markets + 90d hourly funding (2026-07-24 expansion)
  options/         # dated full-chain snapshots (CBOE + Deribit) + DVOL history
                   # (exploratory options-RV study, 2026-07-25 — see below)
data/processed/    # analysis tables built by scripts/analyze_*.py and build_expansion.py
                   # expansion_{funding_panel,stats,cross_venue}.parquet = cross-venue
                   # normalized funding study incl. crypto perps (2026-07-24)
scripts/           # rerunnable collectors + analysis (use .venv/bin/python)
report/            # final report + working notes
```

## Conventions

- Python: `.venv/bin/python` (pandas 3.x, pyarrow). All timestamps UTC.
- Snapshot tables carry a `collected_at` column. Collection date of record: 2026-07-11 (Saturday —
  live snapshots reflect weekend conditions; equity oracles pinned at Friday 2026-07-10 close).
- Funding rates: stored as per-interval decimal rates as reported by each venue; annualization
  noted per table in the report's data dictionary.

## Methodology (LOCKED)

See **`METHODOLOGY.md`** — the locked pipeline spec with decision log:
step 1 universe selection (`scripts/universe.py` → `universe_v2.parquet`, 81 markets
as of 2026-07-24), step 2 market data layer (`scripts/load_market_data.py` →
`market_panel_v2.parquet` + QC). Studies consume those outputs; never re-implement
screens or read raw files directly. Changes require Derek's sign-off + a log entry.

## Expansion study (2026-07-24)

Cross-venue funding-harvest study incl. crypto perps: `scripts/collect_hl_expansion.py`
(HL main-dex funding + predictedFundings), `collect_dydx.py`, `collect_lighter.py`,
`collect_aster_crypto.py`, `collect_extended_all.py`; analysis in `build_expansion.py`
(normalizes all venues to hourly decimal rates, positive = longs pay shorts).
Venue legitimacy research: `report/notes/venue-legitimacy-2026-07.md`.
Deliverable artifact: https://claude.ai/code/artifact/2a208c54-09da-47d8-bd4c-274055160d9b
Unit notes: Lighter /fundings `rate` is PERCENT per hour (verified vs HL overlap);
Aster funding interval inferred per symbol from timestamp gaps; Drift API geo-blocked.

## Options RV study (exploratory, 2026-07-25 — NOT in METHODOLOGY)

Step-4 candidate: express the hedge leg via options. `scripts/collect_options.py`
(hourly dated snapshots: CBOE US chains, Deribit BTC/ETH + USDC-linear SOL/HYPE,
DVOL history) and `scripts/options_rv.py` (put-call-parity implied carry/borrow vs
operative funding = synthetic-forward edge; 75-delta theta drag = convex-hedge cost).
Formalization awaits review of RV results on a fresh RTH snapshot (weekend chains are
stale vs spot — PCP unreliable then).
