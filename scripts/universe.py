"""Canonical universe selection — v2 (Derek, 2026-07-24).

THE rule. Docs (README.md / CLAUDE.md) describe it; this file defines it.
Any study (backtests, forecasts, dashboards) should import select_universe()
or read data/processed/universe_v2.parquet rather than re-implementing screens.

Rule v2:
  1. Venues: hyperliquid (main), hl_xyz, lighter — the legitimacy-screened set
     (see report/notes/venue-legitimacy-2026-07.md for why others are excluded).
  2. >=21 days of funding history.
  3. Memecoins excluded (curated set in build_expansion.MEMES).
  4. Crypto whitelist: BTC/ETH/SOL on any venue, HYPE on hyperliquid only,
     LIT on lighter only. ALL other crypto excluded (incl. XMR — Derek's call).
  5. Liquidity: 24h volume >= $1M AND open interest > $1M (live snapshot).
  6. NO funding-rate cutoff — negative-carry names are long-perp candidates.

Volume/OI are snapshot-dependent: rerun after each data refresh; names cut on
depth (e.g. SOXL/SAMSUNG/QQQ/TSLA on Lighter) re-enter if their books grow.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT = "/Users/dereklou/Projects/equity-perp/data/processed"
VENUES = ["hyperliquid", "hl_xyz", "lighter"]
MIN_SPAN_DAYS = 21
MIN_VOL_USD = 1e6
MIN_OI_USD = 1e6
CRYPTO_ANY = {"BTC", "ETH", "SOL"}
CRYPTO_VENUE = {("hyperliquid", "HYPE"), ("lighter", "LIT")}


def base_name(symbol: str) -> str:
    x = symbol.split(":")[-1]
    return x.removesuffix("USD") if len(x) > 4 and x.endswith("USD") else x


def crypto_whitelisted(venue: str, symbol: str) -> bool:
    b = base_name(symbol)
    return b in CRYPTO_ANY or (venue, b) in CRYPTO_VENUE


def select_universe(stats: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    """stats = expansion_stats.parquet, panel = expansion_funding_panel.parquet.
    Returns one row per in-universe (venue, symbol) with status for cut rows too.
    """
    p = panel[panel.venue.isin(VENUES)]
    full = (p.groupby(["venue", "symbol"])
            .agg(avg_rate_1h=("rate_1h", "mean"),
                 t0=("time", "min"), t1=("time", "max")).reset_index())
    full["span_days"] = (full.t1 - full.t0).dt.days
    full["avg_funding_ann"] = full.avg_rate_1h * 24 * 365
    full = full[full.span_days >= MIN_SPAN_DAYS]

    st = stats[stats.venue.isin(VENUES)][
        ["venue", "symbol", "category", "ann_funding_30d", "ann_funding_90d",
         "pct_days_pos_90d", "vol24h_usd", "oi_usd"]]
    df = full.merge(st, on=["venue", "symbol"], how="left")
    df = df[df.category != "memecoin"]

    def status(row):
        is_crypto = (row["category"] in ("major_crypto", "alt_crypto")
                     or not isinstance(row["category"], str))
        if is_crypto and not crypto_whitelisted(row["venue"], row["symbol"]):
            return "cut_crypto_whitelist"
        if pd.isna(row["vol24h_usd"]) or row["vol24h_usd"] < MIN_VOL_USD:
            return "cut_volume"
        if pd.isna(row["oi_usd"]) or row["oi_usd"] <= MIN_OI_USD:
            return "cut_oi"
        return "in"

    df["status"] = df.apply(status, axis=1)
    df["in_universe"] = df.status == "in"
    return df.drop(columns=["avg_rate_1h", "t0", "t1"])


def main():
    stats = pd.read_parquet(f"{OUT}/expansion_stats.parquet")
    panel = pd.read_parquet(f"{OUT}/expansion_funding_panel.parquet")
    df = select_universe(stats, panel)
    df.to_parquet(f"{OUT}/universe_v2.parquet", index=False)
    inu = df[df.in_universe]
    print(f"universe v2: {len(inu)} in / {len(df)} candidates")
    print(inu.groupby("venue").size().to_string())
    print(inu.groupby("category").size().to_string())


if __name__ == "__main__":
    main()
