"""Funding-deviation tradeability analysis on hourly-funding venues (HL builder dexes, Vest, Aster).

Questions answered:
  1. Persistence: AR(1) of hourly funding, half-life of deviations from each asset's mean.
  2. Threshold frequency: % of hours with trailing-24h funding annualized beyond +/-20%, +/-50%.
  3. Simple rule backtest (funding-capture only, price-hedged assumed):
     enter short-perp basis when trailing-24h ann funding > entry_thr, exit when trailing-24h < exit_thr;
     P&L = funding accrued while in position - round-trip costs. Symmetric for negative funding.
     Reports per-asset: trades/yr, avg holding days, gross funding captured, net ann return on notional.

Outputs: data/processed/deviation_stats.parquet, data/processed/funding_capture_backtest.parquet
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data/raw", ROOT / "data/processed"
HOURS_YR = 24 * 365

fs = pd.read_parquet(OUT / "funding_stats.parquet")
UNIVERSE = fs[(fs["asset_class"] != "crypto") & (fs["n_obs"] >= 24 * 30)]
UNIVERSE = set(zip(UNIVERSE["venue"], UNIVERSE["symbol"]))

panels = []
hl = pd.read_parquet(RAW / "hyperliquid/funding_history.parquet")
hl["venue"] = "hyperliquid:" + hl["dex"]
panels.append(hl.rename(columns={"coin": "symbol", "fundingRate": "hourly_rate"})[["venue", "symbol", "time", "hourly_rate"]])
v = pd.read_parquet(RAW / "longtail/vest_funding_history.parquet")
v["venue"] = "vest"
panels.append(v.rename(columns={"oneHrFundingRate": "hourly_rate"})[["venue", "symbol", "time", "hourly_rate"]])
a = pd.read_parquet(RAW / "longtail/aster_funding_history.parquet").sort_values(["symbol", "fundingTime"])
iv = a.groupby("symbol")["fundingTime"].diff().dt.total_seconds().div(3600)
a["interval_h"] = iv.groupby(a["symbol"]).transform("median").fillna(8).clip(1, 24)
a["hourly_rate"] = a["fundingRate"] / a["interval_h"]
a["venue"] = "aster"
panels.append(a.rename(columns={"fundingTime": "time"})[["venue", "symbol", "time", "hourly_rate"]])
e = pd.read_parquet(RAW / "longtail/extended_funding_history.parquet")
e["venue"] = "extended"
panels.append(e.rename(columns={"market": "symbol", "fundingRate": "hourly_rate"})[["venue", "symbol", "time", "hourly_rate"]])
fund = pd.concat(panels, ignore_index=True)
fund["time"] = pd.to_datetime(fund["time"], utc=True)
fund = fund[[t in UNIVERSE for t in zip(fund["venue"], fund["symbol"])]]

FEES = {"hyperliquid": 0.00045, "vest": 0.0005, "aster": 0.00035}
HEDGE_RT = 0.0004          # spot/CFD hedge round trip
ENTRY, EXIT = 0.20, 0.05   # annualized trailing-24h thresholds

fund["time"] = fund["time"].dt.floor("h")

dev_rows, bt_rows = [], []
for (venue, sym), g in fund.groupby(["venue", "symbol"]):
    g = g.sort_values("time").drop_duplicates("time").set_index("time")
    r = g["hourly_rate"].dropna()
    span_days = (r.index.max() - r.index.min()).total_seconds() / 86400
    if len(r) < 90 or span_days < 30:
        continue
    interval_h = max(r.index.to_series().diff().dt.total_seconds().div(3600).median(), 1.0)
    # per-observation accrued funding fraction (rate is hourly; obs every interval_h)
    dt_h = r.index.to_series().diff().shift(-1).dt.total_seconds().div(3600).clip(upper=3 * interval_h).fillna(interval_h)
    accrual = r * dt_h.values
    trail = r.rolling("24h", min_periods=max(3, int(12 / interval_h))).mean() * HOURS_YR
    ar1 = r.autocorr(1)
    hl_hours = np.log(0.5) / np.log(abs(ar1)) * interval_h if ar1 and 0 < ar1 < 1 else np.nan
    dev_rows.append({
        "venue": venue, "symbol": sym, "n_obs": len(r), "span_days": span_days,
        "interval_h": interval_h, "ar1": ar1, "half_life_hours": hl_hours,
        "pct_trail24_gt_20": (trail > 0.20).mean(), "pct_trail24_lt_m20": (trail < -0.20).mean(),
        "pct_trail24_gt_50": (trail > 0.50).mean(), "pct_trail24_lt_m50": (trail < -0.50).mean(),
    })
    # rule backtest on both sides
    fee_rt = 2 * FEES.get(venue.split(":")[0], 0.0005) + HEDGE_RT
    yrs = span_days / 365
    for side in (1, -1):  # 1 = capture positive funding (short perp), -1 = negative
        sig = side * trail
        in_pos, entry_t, pnl_acc, trades = False, None, 0.0, []
        for t, s_val, acc in zip(r.index, sig.values, accrual.values):
            if not in_pos and s_val > ENTRY:
                in_pos, entry_t, pnl_acc = True, t, 0.0
            elif in_pos:
                pnl_acc += side * acc
                if s_val < EXIT:
                    trades.append((entry_t, t, pnl_acc - fee_rt))
                    in_pos = False
        if in_pos:
            trades.append((entry_t, r.index[-1], pnl_acc - fee_rt))
        if trades:
            tr = pd.DataFrame(trades, columns=["entry", "exit", "net_pnl"])
            tr["hold_days"] = (tr["exit"] - tr["entry"]).dt.total_seconds() / 86400
            bt_rows.append({
                "venue": venue, "symbol": sym, "side": "short_perp" if side == 1 else "long_perp",
                "n_trades": len(tr), "trades_per_yr": len(tr) / yrs,
                "avg_hold_days": tr["hold_days"].mean(),
                "win_rate": (tr["net_pnl"] > 0).mean(),
                "total_net_pnl_on_notional": tr["net_pnl"].sum(),
                "ann_net_return_on_notional": tr["net_pnl"].sum() / yrs,
                "time_in_market": tr["hold_days"].sum() / (yrs * 365),
            })

dev = pd.DataFrame(dev_rows)
bt = pd.DataFrame(bt_rows)
dev.to_parquet(OUT / "deviation_stats.parquet", index=False)
bt.to_parquet(OUT / "funding_capture_backtest.parquet", index=False)

pd.set_option("display.width", 250, "display.max_rows", 80, "display.float_format", lambda x: f"{x:,.3g}")
print("== persistence / threshold stats (sorted by % time |trail24| beyond 20% ann) ==")
dev["pct_beyond20"] = dev["pct_trail24_gt_20"] + dev["pct_trail24_lt_m20"]
print(dev.sort_values("pct_beyond20", ascending=False).head(25).to_string(index=False))
print("\n== funding-capture rule backtest: top 25 by annualized net return (entry 20%/exit 5%, incl fees) ==")
print(bt.sort_values("ann_net_return_on_notional", ascending=False).head(25).to_string(index=False))
print("\n== aggregate: median across assets by venue ==")
print(bt.groupby(["venue", "side"])[["trades_per_yr", "avg_hold_days", "win_rate", "ann_net_return_on_notional", "time_in_market"]].median())
