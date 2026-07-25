"""Liquidation-fade proxy: do large 1h moves on xyz top names mean-revert, and when?

We have no liquidation flags in the collected data (needs HL node/WS feed), so this uses
large hourly moves as a proxy for forced flow, split by session: during US RTH a large move
is usually news being priced (expect continuation); off-hours/weekends the cash market is
closed, so large moves are flow-driven (liquidations, retail bursts) against thin books
(expect reversion).

Output: data/processed/reversal_stats.parquet
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
h = pd.read_parquet(ROOT / "data/raw/hyperliquid/hourly_candles_top.parquet")
tcol = [c for c in h.columns if c in ("t", "time", "openTime", "date")][0]
h["time"] = pd.to_datetime(h[tcol], utc=True)
h = h.sort_values(["coin", "time"])
h["ret"] = h.groupby("coin")["c"].pct_change()
h["fwd1"] = h.groupby("coin")["ret"].shift(-1)
h["fwd3"] = h.groupby("coin")["c"].shift(-3) / h["c"] - 1
et = h["time"].dt.tz_convert("America/New_York")
h["sess"] = np.where(et.dt.dayofweek >= 5, "weekend",
                     np.where((et.dt.hour >= 10) & (et.dt.hour < 16) & (et.dt.dayofweek < 5), "rth", "overnight"))

big = h[h["ret"].abs() > 0.01].copy()
big["rev1"] = -np.sign(big["ret"]) * big["fwd1"]
big["rev3"] = -np.sign(big["ret"]) * big["fwd3"]
big["bucket"] = pd.cut(big["ret"].abs(), [0.01, 0.015, 0.02, 0.03, 1], labels=["1-1.5%", "1.5-2%", "2-3%", ">3%"])

out = pd.concat([
    big.groupby("sess")[["rev1", "rev3"]].agg(["mean", "std", "count"]),
    big.groupby("bucket", observed=True)[["rev1", "rev3"]].agg(["mean", "std", "count"]),
])
out.columns = ["_".join(c) for c in out.columns]
out = out.reset_index(names="group")
out.to_parquet(ROOT / "data/processed/reversal_stats.parquet", index=False)
print(out.round(4).to_string(index=False))
print(f"\nn={len(big)} events over {h.time.min():%Y-%m-%d}..{h.time.max():%Y-%m-%d}, {h.coin.nunique()} coins (top-15 xyz by volume)")
print("t-stat overnight rev1:", round(big[big.sess=='overnight'].rev1.mean()/(big[big.sess=='overnight'].rev1.std()/np.sqrt((big.sess=='overnight').sum())), 2))
