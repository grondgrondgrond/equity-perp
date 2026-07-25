"""Collect Hyperliquid perp dex list + per-dex asset context snapshots.

Outputs (idempotent, overwritten each run):
  data/raw/hyperliquid/perp_dexs.parquet
  data/raw/hyperliquid/dex_oi_caps.parquet
  data/raw/hyperliquid/asset_ctx_snapshot.parquet
"""
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hl_common import OUT_DIR, classify_asset, post

FLOAT_CTX_COLS = [
    "funding", "openInterest", "prevDayPx", "dayNtlVlm", "premium",
    "oraclePx", "markPx", "midPx", "dayBaseVlm",
]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    collected_at = pd.Timestamp.now(tz="UTC")

    # ---------------------------------------------------------- perpDexs
    dexs_raw = post({"type": "perpDexs"})
    dex_rows, cap_rows = [], []
    dex_names = [""]  # main dex, represented by null in perpDexs
    for d in dexs_raw:
        if d is None:
            continue
        dex_names.append(d["name"])
        dex_rows.append({
            "name": d["name"],
            "fullName": d.get("fullName"),
            "deployer": d.get("deployer"),
            "oracleUpdater": d.get("oracleUpdater"),
            "feeRecipient": d.get("feeRecipient"),
            "collected_at": collected_at,
        })
        for asset, cap in (d.get("assetToStreamingOiCap") or []):
            cap_rows.append({
                "dex": d["name"], "asset": asset, "oi_cap": float(cap),
                "collected_at": collected_at,
            })

    perp_dexs = pd.DataFrame(dex_rows)
    oi_caps = pd.DataFrame(cap_rows)
    perp_dexs.to_parquet(f"{OUT_DIR}/perp_dexs.parquet", index=False)
    oi_caps.to_parquet(f"{OUT_DIR}/dex_oi_caps.parquet", index=False)
    print(f"perp_dexs: {len(perp_dexs)} rows -> perp_dexs.parquet")
    print(f"dex_oi_caps: {len(oi_caps)} rows -> dex_oi_caps.parquet")

    # ------------------------------------------- metaAndAssetCtxs per dex
    snap_rows = []
    for dex in dex_names:
        time.sleep(0.15)
        meta, ctxs = post({"type": "metaAndAssetCtxs", "dex": dex})
        universe = meta["universe"]
        assert len(universe) == len(ctxs), f"{dex}: universe/ctx length mismatch"
        for a, c in zip(universe, ctxs):
            impact = c.get("impactPxs") or [None, None]
            row = {
                "dex": dex,
                "name": a["name"],
                "szDecimals": a.get("szDecimals"),
                "maxLeverage": a.get("maxLeverage"),
                "isDelisted": bool(a.get("isDelisted", False)),
                "marginTableId": a.get("marginTableId"),
                "asset_class": classify_asset(a["name"]),
                "impactPxBid": float(impact[0]) if impact[0] else None,
                "impactPxAsk": float(impact[1]) if impact[1] else None,
                "collected_at": collected_at,
            }
            for col in FLOAT_CTX_COLS:
                v = c.get(col)
                row[col] = float(v) if v is not None else None
            snap_rows.append(row)
        print(f"dex={dex or '(main)'}: {len(universe)} assets")

    snap = pd.DataFrame(snap_rows)
    snap.to_parquet(f"{OUT_DIR}/asset_ctx_snapshot.parquet", index=False)
    print(f"asset_ctx_snapshot: {len(snap)} rows -> asset_ctx_snapshot.parquet")

    # ------------------------------------------------------------ sanity
    nvda = snap[snap["name"] == "xyz:NVDA"]
    if not nvda.empty:
        print(f"sanity xyz:NVDA markPx={nvda.iloc[0]['markPx']}")
    print(snap.groupby(["dex"])[["dayNtlVlm", "openInterest"]].count())


if __name__ == "__main__":
    main()
