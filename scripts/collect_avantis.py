#!/usr/bin/env python
"""Collect Avantis (avantisfi.com, Base) market data: pair snapshot + history.

Sources (all public, no auth; discovered via Avantis-Labs GitHub —
avantis_trader_sdk config + avantis-trading-skill API docs + DefiLlama adapters):
- Snapshot: GET https://data.avantisfi.com/v2/trading
  (all values human-decimal: USDC dollars, plain percent, plain leverage;
   marginFee.long/.short is the HOURLY margin-fee percent per side)
  Same payload also at https://socket-api-pub.avantisfi.com/socket-api/v1/data
- History:  GET https://api.avantisfi.com/v1/cached/history/analytics/{metric}/{days}
  metrics: daily-volumes, open-interest-snapshot, total-fees, tvl, unique-traders
  (server caps history at ~366 days; rate limit ~10 req/s per IP)

Outputs (data/raw/longtail/):
- avantis_pairs_snapshot.parquet         one row per pair
- avantis_history_daily_volumes.parquet  daily platform volume (USDC)
- avantis_history_open_interest.parquet  daily OI snapshot long/short totals
- avantis_history_fees.parquet           daily fee breakdown
- avantis_history_tvl.parquet            daily LP TVL (junior/senior tranches)
- avantis_history_traders.parquet        daily active/new trader counts

Rerunnable; full overwrite each run; `collected_at` in UTC.
"""

import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "longtail"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DATA_URL = "https://data.avantisfi.com/v2/trading"
HIST_URL = "https://api.avantisfi.com/v1/cached/history/analytics/{metric}/{days}"
HIST_DAYS = 400  # server caps at ~366

HOURS_PER_YEAR = 24 * 365

# Avantis puts all equities+ETFs+index products in one EQUITIES group;
# split index/ETF products from single stocks for asset_class.
INDEX_ETF_TICKERS = {
    "US500", "US30", "US100", "US2000", "SPX", "NDX", "DJI", "RUT",
    "SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "GDX", "URA", "URNM", "VIX",
}

GROUP_CLASS = {
    "CRYPTO1": "crypto", "CRYPTO2": "crypto", "CRYPTO3": "crypto", "CRYPTO4": "crypto",
    "FOREX": "forex", "COMMODITIES": "commodities", "EQUITIES": "equities",
}


def fetch_json(url: str) -> dict:
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": "research-collector/1.0"})
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))


def collect_snapshot(collected_at: str) -> pd.DataFrame:
    d = fetch_json(DATA_URL)
    groups = d["groupInfo"]
    rows = []
    for idx, p in d["pairInfos"].items():
        g = groups[str(p["groupIndex"])]
        gname = g["name"]
        acls = GROUP_CLASS.get(gname, "other")
        if acls == "equities":
            acls = "indices" if p["from"] in INDEX_ETF_TICKERS else "stocks"
        feed_attrs = (p.get("feed") or {}).get("attributes") or {}
        mf = p.get("marginFee") or {}
        oi = p.get("openInterest") or {}
        sp = p.get("storagePairParams") or {}
        depth = p.get("pairParams") or {}
        lev = p.get("leverages") or {}
        pair_oi = p.get("pairOI")
        pair_max_oi = p.get("pairMaxOI")
        rows.append({
            "pair_index": int(idx),
            "pair": f"{p['from']}/{p['to']}",
            "base": p["from"],
            "quote": p["to"],
            "group_index": int(p["groupIndex"]),
            "group_name": gname,
            "asset_class": acls,
            "is_listed": p.get("isPairListed", True),
            "feed_symbol": feed_attrs.get("symbol"),
            "market_open_now": feed_attrs.get("isOpen", feed_attrs.get("is_open")),
            "next_open_ts": feed_attrs.get("nextOpen", feed_attrs.get("next_open")),
            "next_close_ts": feed_attrs.get("nextClose", feed_attrs.get("next_close")),
            "min_leverage": lev.get("minLeverage"),
            "max_leverage": lev.get("maxLeverage"),
            "zfp_min_leverage": lev.get("pnlMinLeverage"),
            "zfp_max_leverage": lev.get("pnlMaxLeverage"),
            "open_fee_pct": p.get("openFeeP"),
            "close_fee_pct": p.get("closeFeeP"),
            "limit_order_fee_pct": p.get("limitOrderFeeP"),
            "spread_pct": p.get("spreadP"),
            "zfp_spread_pct": p.get("pnlSpreadP"),
            "one_pct_depth_above_usd": depth.get("onePercentDepthAbove"),
            "one_pct_depth_below_usd": depth.get("onePercentDepthBelow"),
            "margin_fee_long_hourly_pct": mf.get("long"),
            "margin_fee_short_hourly_pct": mf.get("short"),
            "margin_fee_long_apr_pct": (mf.get("long") or 0) * HOURS_PER_YEAR,
            "margin_fee_short_apr_pct": (mf.get("short") or 0) * HOURS_PER_YEAR,
            "min_borrow_fee_raw": sp.get("minBorrowFee"),
            "max_borrow_fee_raw": sp.get("maxBorrowFee"),
            "oi_long_usd": oi.get("long"),
            "oi_short_usd": oi.get("short"),
            "pair_oi_usd": pair_oi,
            "pair_max_oi_usd": pair_max_oi,
            "oi_utilization": (pair_oi / pair_max_oi) if pair_max_oi else None,
            "max_wallet_oi_usd": p.get("maxWalletOI"),
            "group_oi_usd": g.get("groupOI"),
            "group_max_oi_usd": g.get("groupMaxOI"),
            "min_lev_pos_usdc": p.get("pairMinLevPosUSDC"),
            "collected_at": collected_at,
        })
    df = pd.DataFrame(rows).sort_values("pair_index").reset_index(drop=True)
    return df


HIST_SPECS = {
    # metric -> (output filename, record flattener)
    "daily-volumes": ("avantis_history_daily_volumes.parquet", lambda r: r),
    "total-fees": ("avantis_history_fees.parquet", lambda r: r),
    "tvl": ("avantis_history_tvl.parquet", lambda r: r),
    "unique-traders": ("avantis_history_traders.parquet", lambda r: r),
    "open-interest-snapshot": (
        "avantis_history_open_interest.parquet",
        lambda r: {"date": r["date"], **{
            "long_total_usd": r["openInterestSnapshot"]["longTotal"],
            "short_total_usd": r["openInterestSnapshot"]["shortTotal"],
            "total_oi_usd": r["openInterestSnapshot"]["totalRatio"],
            "skew_distance_usd": r["openInterestSnapshot"]["skewDistance"],
        }},
    ),
}


def collect_history(collected_at: str) -> None:
    for metric, (fname, flatten) in HIST_SPECS.items():
        d = fetch_json(HIST_URL.format(metric=metric, days=HIST_DAYS))
        if not d.get("success"):
            print(f"WARN: history metric {metric} failed: {d}")
            continue
        df = pd.DataFrame([flatten(r) for r in d["history"]])
        df["collected_at"] = collected_at
        out = OUT_DIR / fname
        df.to_parquet(out, index=False)
        print(f"wrote {out} rows={len(df)}")
        time.sleep(1.0)  # polite (~10 req/s limit)


def main():
    collected_at = datetime.now(timezone.utc).isoformat()
    df = collect_snapshot(collected_at)
    out = OUT_DIR / "avantis_pairs_snapshot.parquet"
    df.to_parquet(out, index=False)
    print(f"wrote {out} rows={len(df)}")
    print(df.groupby("asset_class").size())
    collect_history(collected_at)


if __name__ == "__main__":
    main()
