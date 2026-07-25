"""Collect Hyperliquid funding-rate history.

Coverage:
  - ALL assets on the xyz dex (incl. delisted): 180 days.
  - All RWA (non-crypto) assets on other builder dexes (incl. delisted): 90 days.

Resumable: each (dex, coin) is written to a temp parquet under
data/raw/hyperliquid/_tmp_funding/ and skipped on rerun; the final
funding_history.parquet is rebuilt from temps at the end. Pass --refresh to
refetch everything from scratch.

Output: data/raw/hyperliquid/funding_history.parquet
        (dex, coin, time, fundingRate, premium)
"""
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hl_common import BUILDER_DEXES, OUT_DIR, classify_asset, post

TMP_DIR = f"{OUT_DIR}/_tmp_funding"
MS_DAY = 86_400_000


def fetch_coin_history(coin: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Paginate fundingHistory by advancing startTime past the last record."""
    frames, cursor = [], start_ms
    while cursor < end_ms:
        time.sleep(0.2)
        recs = post({"type": "fundingHistory", "coin": coin,
                     "startTime": cursor, "endTime": end_ms})
        if not recs:
            break
        frames.append(pd.DataFrame(recs))
        last = recs[-1]["time"]
        if last <= cursor and len(recs) < 500:
            break
        cursor = last + 1
        if len(recs) < 500 and cursor >= end_ms:
            break
        if len(recs) < 500:
            break  # short page => history exhausted
    if not frames:
        return pd.DataFrame(columns=["coin", "fundingRate", "premium", "time"])
    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["time"])
    return df


def main():
    refresh = "--refresh" in sys.argv
    os.makedirs(TMP_DIR, exist_ok=True)
    now_ms = int(time.time() * 1000)

    # Build target coin list from live universes.
    targets = []  # (dex, coin, lookback_days)
    for dex in BUILDER_DEXES:
        time.sleep(0.15)
        meta, _ = post({"type": "metaAndAssetCtxs", "dex": dex})
        for a in meta["universe"]:
            coin = a["name"]
            if dex == "xyz":
                targets.append((dex, coin, 180))
            elif classify_asset(coin) != "crypto":
                targets.append((dex, coin, 90))
    print(f"target coins: {len(targets)}")

    for i, (dex, coin, days) in enumerate(targets, 1):
        safe = coin.replace(":", "__").replace("/", "_")
        tmp_path = f"{TMP_DIR}/{safe}.parquet"
        if os.path.exists(tmp_path) and not refresh:
            continue
        df = fetch_coin_history(coin, now_ms - days * MS_DAY, now_ms)
        df["dex"] = dex
        if "coin" not in df.columns or df.empty:
            df = pd.DataFrame({"coin": pd.Series([], dtype=str),
                               "fundingRate": [], "premium": [], "time": [],
                               "dex": pd.Series([], dtype=str)})
            df["coin"] = coin
        df.to_parquet(tmp_path, index=False)
        print(f"[{i}/{len(targets)}] {coin}: {len(df)} rows")

    # ------------------------------------------------------- final concat
    frames = []
    for f in sorted(os.listdir(TMP_DIR)):
        if f.endswith(".parquet"):
            frames.append(pd.read_parquet(f"{TMP_DIR}/{f}"))
    out = pd.concat(frames, ignore_index=True)
    out = out[out["time"].notna()]
    out["fundingRate"] = out["fundingRate"].astype(float)
    out["premium"] = pd.to_numeric(out["premium"], errors="coerce")
    out["time"] = pd.to_datetime(out["time"].astype("int64"), unit="ms", utc=True)
    out = out[["dex", "coin", "time", "fundingRate", "premium"]]
    out = out.sort_values(["dex", "coin", "time"]).reset_index(drop=True)
    out.to_parquet(f"{OUT_DIR}/funding_history.parquet", index=False)
    print(f"funding_history: {len(out)} rows, {out['coin'].nunique()} coins, "
          f"{out['time'].min()} .. {out['time'].max()}")


if __name__ == "__main__":
    main()
