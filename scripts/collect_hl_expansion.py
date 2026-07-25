"""Expansion collector: Hyperliquid MAIN-DEX crypto perps + cross-venue predicted funding.

Adds what the 2026-07-11 RWA study skipped:
  - asset_ctx_snapshot_latest.parquet : fresh snapshot for main dex + all builder dexes
  - predicted_fundings.parquet       : HL vs Binance vs Bybit predicted funding per coin
  - funding_history_maindex.parquet  : 120d hourly funding for top main-dex coins
                                       (top ~80 by day notional volume ∪ top 40 by |funding|)

Resumable via data/raw/hyperliquid/_tmp_funding_main/; --refresh refetches.
"""
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hl_common import BUILDER_DEXES, OUT_DIR, classify_asset, post

TMP_DIR = f"{OUT_DIR}/_tmp_funding_main"
MS_DAY = 86_400_000
LOOKBACK_DAYS = 120


def fetch_coin_history(coin: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    frames, cursor = [], start_ms
    while cursor < end_ms:
        time.sleep(0.2)
        recs = post({"type": "fundingHistory", "coin": coin,
                     "startTime": cursor, "endTime": end_ms})
        if not recs:
            break
        frames.append(pd.DataFrame(recs))
        last = recs[-1]["time"]
        if len(recs) < 500:
            break
        cursor = last + 1
    if not frames:
        return pd.DataFrame(columns=["coin", "fundingRate", "premium", "time"])
    return pd.concat(frames, ignore_index=True).drop_duplicates(subset=["time"])


def snapshot_all_dexes(collected_at):
    rows = []
    for dex in [""] + BUILDER_DEXES:
        time.sleep(0.15)
        meta, ctxs = post({"type": "metaAndAssetCtxs", "dex": dex})
        for a, c in zip(meta["universe"], ctxs):
            rows.append({
                "dex": dex, "name": a["name"],
                "maxLeverage": a.get("maxLeverage"),
                "isDelisted": a.get("isDelisted", False),
                "asset_class": classify_asset(a["name"]),
                "funding": pd.to_numeric(c.get("funding"), errors="coerce"),
                "openInterest": pd.to_numeric(c.get("openInterest"), errors="coerce"),
                "dayNtlVlm": pd.to_numeric(c.get("dayNtlVlm"), errors="coerce"),
                "premium": pd.to_numeric(c.get("premium"), errors="coerce"),
                "oraclePx": pd.to_numeric(c.get("oraclePx"), errors="coerce"),
                "markPx": pd.to_numeric(c.get("markPx"), errors="coerce"),
                "midPx": pd.to_numeric(c.get("midPx"), errors="coerce"),
                "impactPxBid": pd.to_numeric((c.get("impactPxs") or [None, None])[0], errors="coerce"),
                "impactPxAsk": pd.to_numeric((c.get("impactPxs") or [None, None])[1], errors="coerce"),
                "collected_at": collected_at,
            })
        print(f"snapshot dex={dex or 'main'}: {len(meta['universe'])} assets")
    df = pd.DataFrame(rows)
    df.to_parquet(f"{OUT_DIR}/asset_ctx_snapshot_latest.parquet", index=False)
    return df


def predicted_fundings(collected_at):
    data = post({"type": "predictedFundings"})
    rows = []
    for coin, venues in data:
        for venue, info in venues:
            if not info:
                continue
            rows.append({
                "coin": coin, "venue": venue,
                "fundingRate": pd.to_numeric(info.get("fundingRate"), errors="coerce"),
                "fundingIntervalHours": info.get("fundingIntervalHours"),
                "collected_at": collected_at,
            })
    df = pd.DataFrame(rows)
    df.to_parquet(f"{OUT_DIR}/predicted_fundings.parquet", index=False)
    print(f"predicted_fundings: {len(df)} rows, {df['coin'].nunique()} coins")


def main():
    refresh = "--refresh" in sys.argv
    os.makedirs(TMP_DIR, exist_ok=True)
    collected_at = pd.Timestamp.now(tz="UTC")
    now_ms = int(time.time() * 1000)

    snap = snapshot_all_dexes(collected_at)
    predicted_fundings(collected_at)

    main_live = snap[(snap.dex == "") & ~snap.isDelisted.fillna(False)].copy()
    by_vlm = main_live.nlargest(80, "dayNtlVlm")["name"]
    by_fund = main_live.reindex(main_live["funding"].abs()
                                .sort_values(ascending=False).index).head(40)["name"]
    targets = sorted(set(by_vlm) | set(by_fund))
    print(f"main-dex funding targets: {len(targets)}")

    for i, coin in enumerate(targets, 1):
        tmp_path = f"{TMP_DIR}/{coin.replace('/', '_')}.parquet"
        if os.path.exists(tmp_path) and not refresh:
            continue
        df = fetch_coin_history(coin, now_ms - LOOKBACK_DAYS * MS_DAY, now_ms)
        if df.empty:
            df = pd.DataFrame({"coin": [coin], "fundingRate": [None],
                               "premium": [None], "time": [None]})
        df.to_parquet(tmp_path, index=False)
        print(f"[{i}/{len(targets)}] {coin}: {len(df)} rows")

    frames = [pd.read_parquet(f"{TMP_DIR}/{f}") for f in sorted(os.listdir(TMP_DIR))
              if f.endswith(".parquet")]
    out = pd.concat(frames, ignore_index=True)
    out = out[out["time"].notna()]
    out["fundingRate"] = out["fundingRate"].astype(float)
    out["premium"] = pd.to_numeric(out["premium"], errors="coerce")
    out["time"] = pd.to_datetime(out["time"].astype("int64"), unit="ms", utc=True)
    out = out[["coin", "time", "fundingRate", "premium"]].sort_values(["coin", "time"])
    out.to_parquet(f"{OUT_DIR}/funding_history_maindex.parquet", index=False)
    print(f"funding_history_maindex: {len(out)} rows, {out['coin'].nunique()} coins, "
          f"{out['time'].min()} .. {out['time'].max()}")


if __name__ == "__main__":
    main()
