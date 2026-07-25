"""Collect Hyperliquid candles.

  1. Daily candles since 2025-01-01 for all xyz assets and all RWA (non-crypto)
     assets on other builder dexes -> daily_candles.parquet
  2. Hourly candles, last 30 days, for the top 15 xyz assets by dayNtlVlm
     (from asset_ctx_snapshot.parquet) -> hourly_candles_top.parquet

Resumable via temp parquets in _tmp_candles/; pass --refresh to refetch.
"""
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hl_common import BUILDER_DEXES, OUT_DIR, classify_asset, post

TMP_DIR = f"{OUT_DIR}/_tmp_candles"
MS_DAY = 86_400_000
DAILY_START_MS = int(pd.Timestamp("2025-01-01", tz="UTC").timestamp() * 1000)

CANDLE_COLS = ["t", "o", "h", "l", "c", "v", "n"]


def fetch_candles(coin: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """candleSnapshot with pagination (max ~5000 candles per response)."""
    frames, cursor = [], start_ms
    while cursor < end_ms:
        time.sleep(0.2)
        recs = post({"type": "candleSnapshot",
                     "req": {"coin": coin, "interval": interval,
                             "startTime": cursor, "endTime": end_ms}})
        if not recs:
            break
        frames.append(pd.DataFrame(recs))
        last_t = recs[-1]["t"]
        if last_t <= cursor or len(recs) < 500:
            break
        cursor = last_t + 1
    if not frames:
        return pd.DataFrame(columns=CANDLE_COLS)
    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["t"])
    for col in ["o", "h", "l", "c", "v"]:
        df[col] = df[col].astype(float)
    df["n"] = df["n"].astype("int64")
    return df[CANDLE_COLS]


def collect_set(targets, interval, start_ms, end_ms, tag):
    """targets: list of (dex, coin). Returns concatenated dataframe."""
    frames = []
    for i, (dex, coin) in enumerate(targets, 1):
        safe = f"{tag}__{coin.replace(':', '__')}"
        tmp_path = f"{TMP_DIR}/{safe}.parquet"
        if os.path.exists(tmp_path) and "--refresh" not in sys.argv:
            frames.append(pd.read_parquet(tmp_path))
            continue
        df = fetch_candles(coin, interval, start_ms, end_ms)
        df["dex"] = dex
        df["coin"] = coin
        df.to_parquet(tmp_path, index=False)
        print(f"[{tag} {i}/{len(targets)}] {coin}: {len(df)} candles")
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def main():
    os.makedirs(TMP_DIR, exist_ok=True)
    now_ms = int(time.time() * 1000)

    # ------------------------------------------------- target coin lists
    daily_targets = []
    for dex in BUILDER_DEXES:
        time.sleep(0.15)
        meta, _ = post({"type": "metaAndAssetCtxs", "dex": dex})
        for a in meta["universe"]:
            coin = a["name"]
            if dex == "xyz" or classify_asset(coin) != "crypto":
                daily_targets.append((dex, coin))
    print(f"daily candle targets: {len(daily_targets)}")

    daily = collect_set(daily_targets, "1d", DAILY_START_MS, now_ms, "d1")
    daily = daily[daily["t"].notna()].copy()
    daily["date"] = pd.to_datetime(daily["t"].astype("int64"), unit="ms", utc=True)
    daily["notional_usd"] = daily["v"] * daily["c"]
    daily = daily[["dex", "coin", "date", "o", "h", "l", "c", "v", "n",
                   "notional_usd"]].sort_values(["dex", "coin", "date"])
    daily.to_parquet(f"{OUT_DIR}/daily_candles.parquet", index=False)
    print(f"daily_candles: {len(daily)} rows, {daily['coin'].nunique()} coins, "
          f"{daily['date'].min()} .. {daily['date'].max()}")

    # ------------------------------------------ hourly for top-15 xyz coins
    snap = pd.read_parquet(f"{OUT_DIR}/asset_ctx_snapshot.parquet")
    top = (snap[(snap["dex"] == "xyz") & (~snap["isDelisted"])]
           .sort_values("dayNtlVlm", ascending=False).head(15))
    hourly_targets = [("xyz", c) for c in top["name"]]
    print("top-15 xyz by dayNtlVlm:", [c for _, c in hourly_targets])

    hourly = collect_set(hourly_targets, "1h", now_ms - 30 * MS_DAY, now_ms, "h1")
    hourly = hourly[hourly["t"].notna()].copy()
    hourly["time"] = pd.to_datetime(hourly["t"].astype("int64"), unit="ms", utc=True)
    hourly["notional_usd"] = hourly["v"] * hourly["c"]
    hourly = hourly[["dex", "coin", "time", "o", "h", "l", "c", "v", "n",
                     "notional_usd"]].sort_values(["dex", "coin", "time"])
    hourly.to_parquet(f"{OUT_DIR}/hourly_candles_top.parquet", index=False)
    print(f"hourly_candles_top: {len(hourly)} rows, "
          f"{hourly['coin'].nunique()} coins, "
          f"{hourly['time'].min()} .. {hourly['time'].max()}")


if __name__ == "__main__":
    main()
