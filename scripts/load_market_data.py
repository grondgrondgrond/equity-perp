"""Step 2 — canonical market-data layer (universe v2).

Pipeline position:
  step 1: scripts/universe.py          -> data/processed/universe_v2.parquet
  step 2: THIS                         -> data/processed/market_panel_v2.parquet
                                          data/processed/market_panel_qc.parquet
  step 3+: backtests / forecasts consume market_panel_v2, never raw files.

For every in-universe (venue, symbol), on a common hourly UTC grid:
  funding_rate_1h : decimal per hour, positive = longs pay shorts
                    (from expansion_funding_panel; HL ms-offset stamps floored)
  close           : venue trade-candle close — the observable mark proxy used
                    for liquidation modeling (HL liquidations actually use an
                    oracle-blended mark; documented approximation)
  ret_1h          : simple close-to-close return

Conventions:
  - NO imputation here. Gaps are NaN; downstream decides how to fill.
  - Grid per market = first to last hour where EITHER series exists.
  - Refresh flow: collect_prices.py universe  ->  this script.

QC output per market: spans, coverage %, largest gap, funding/price overlap.
"""
import numpy as np
import pandas as pd

OUT = "/Users/dereklou/Projects/equity-perp/data/processed"
RAW = "/Users/dereklou/Projects/equity-perp/data/raw"


def load_prices() -> dict:
    px = {}
    hl = pd.read_parquet(f"{RAW}/hyperliquid/candles_1h_bt.parquet")
    for coin, g in hl.groupby("coin"):
        venue = "hl_xyz" if coin.startswith("xyz:") else "hyperliquid"
        px[(venue, coin)] = g.set_index("time")["close"].sort_index()
    ltr = pd.read_parquet(f"{RAW}/lighter/candles_1h.parquet")
    for sym, g in ltr.groupby("symbol"):
        px[("lighter", sym)] = pd.to_numeric(
            g.set_index("time")["close"]).sort_index()
    return px


def build_panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    uni = pd.read_parquet(f"{OUT}/universe_v2.parquet")
    uni = uni[uni.in_universe]
    fund = pd.read_parquet(f"{OUT}/expansion_funding_panel.parquet")
    fund["time"] = fund["time"].dt.floor("h")
    px = load_prices()

    frames, qc = [], []
    for r in uni.itertuples():
        key = (r.venue, r.symbol)
        f = (fund[(fund.venue == r.venue) & (fund.symbol == r.symbol)]
             .groupby("time")["rate_1h"].sum().sort_index())
        p = px.get(key)
        if p is None or p.empty:
            qc.append({"venue": r.venue, "symbol": r.symbol, "status": "NO_PRICES",
                       "fund_hours": len(f)})
            continue
        p = p[~p.index.duplicated()]
        t0 = min(f.index.min(), p.index.min())
        t1 = max(f.index.max(), p.index.max())
        grid = pd.date_range(t0, t1, freq="h", tz="UTC")
        df = pd.DataFrame({"time": grid,
                           "funding_rate_1h": f.reindex(grid).to_numpy(),
                           "close": p.reindex(grid).to_numpy()})
        df["ret_1h"] = df["close"].pct_change()
        df.insert(0, "symbol", r.symbol)
        df.insert(0, "venue", r.venue)
        frames.append(df)

        both = df.funding_rate_1h.notna() & df.close.notna()
        gaps = (~df.close.notna()).astype(int)
        # largest run of consecutive missing price hours
        runs = gaps.groupby((gaps == 0).cumsum()).sum()
        qc.append({
            "venue": r.venue, "symbol": r.symbol, "status": "OK",
            "grid_hours": len(grid),
            "fund_cov": round(df.funding_rate_1h.notna().mean(), 3),
            "px_cov": round(df.close.notna().mean(), 3),
            "overlap_hours": int(both.sum()),
            "overlap_days": round(both.sum() / 24, 1),
            "max_px_gap_h": int(runs.max()) if len(runs) else 0,
            "t0": t0, "t1": t1,
        })

    panel = pd.concat(frames, ignore_index=True)
    qc_df = pd.DataFrame(qc)
    panel.to_parquet(f"{OUT}/market_panel_v2.parquet", index=False)
    qc_df.to_parquet(f"{OUT}/market_panel_qc.parquet", index=False)
    return panel, qc_df


def main():
    panel, qc = build_panel()
    pd.set_option("display.width", 220)
    ok = qc[qc.status == "OK"]
    missing = qc[qc.status != "OK"]
    print(f"panel: {len(panel):,} rows, {len(ok)} markets OK, "
          f"{len(missing)} missing prices")
    if len(missing):
        print("MISSING PRICES:", missing[["venue", "symbol"]].to_records(index=False))
    print("\ncoverage summary:")
    print(ok.groupby("venue").agg(mkts=("symbol", "count"),
                                  med_overlap_d=("overlap_days", "median"),
                                  min_overlap_d=("overlap_days", "min"),
                                  med_px_cov=("px_cov", "median"),
                                  worst_px_gap_h=("max_px_gap_h", "max")).to_string())
    thin = ok[(ok.px_cov < 0.8) | (ok.overlap_days < 30)]
    if len(thin):
        print("\nFLAG — thin coverage (<80% price cov or <30d overlap):")
        print(thin[["venue", "symbol", "overlap_days", "px_cov", "max_px_gap_h"]]
              .to_string(index=False))


if __name__ == "__main__":
    main()
