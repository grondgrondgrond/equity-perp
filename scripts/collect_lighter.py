"""Collect Lighter (zk L2 perp CLOB, mainnet.zklighter.elliot.ai) markets + funding.

Outputs (data/raw/lighter/):
  lighter_markets.parquet          - orderBookDetails snapshot (OI, 24h volume, clamps)
  lighter_funding_history.parquet  - 90d hourly funding for top markets by quote volume

NOTE on units: /fundings returns {rate, direction}. Direction 'long' means longs pay.
Rate units verified against Hyperliquid same-coin/same-hour during analysis
(build_expansion.py) rather than assumed here; stored raw with sign applied
(positive = longs pay shorts).
"""
import os
import time

import pandas as pd
import requests

BASE = "https://mainnet.zklighter.elliot.ai/api/v1"
OUT = "/Users/dereklou/Projects/equity-perp/data/raw/lighter"
LOOKBACK_DAYS = 90
TOP_N = 60

sess = requests.Session()
sess.headers["User-Agent"] = "equity-perp-research/1.0"


def get(path, params=None, tries=5):
    for i in range(tries):
        try:
            r = sess.get(BASE + path, params=params, timeout=30)
        except requests.RequestException:
            time.sleep(2 * (i + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(3 * (i + 1))
            continue
        r.raise_for_status()
        time.sleep(0.1)
        return r.json()
    raise RuntimeError(f"failed: {path} {params}")


def main():
    os.makedirs(OUT, exist_ok=True)
    collected_at = pd.Timestamp.now(tz="UTC")

    det = get("/orderBookDetails")["order_book_details"]
    rows = []
    for d in det:
        rows.append({
            "symbol": d["symbol"], "market_id": d["market_id"],
            "status": d["status"],
            "mark_price": pd.to_numeric(d.get("mark_price"), errors="coerce"),
            "index_price": pd.to_numeric(d.get("index_price"), errors="coerce"),
            "daily_quote_volume": pd.to_numeric(d.get("daily_quote_token_volume"), errors="coerce"),
            "daily_trades": d.get("daily_trades_count"),
            "open_interest_base": pd.to_numeric(d.get("open_interest"), errors="coerce"),
            "funding_clamp_small": pd.to_numeric(d.get("funding_clamp_small"), errors="coerce"),
            "funding_clamp_big": pd.to_numeric(d.get("funding_clamp_big"), errors="coerce"),
            "base_interest_rate": pd.to_numeric(d.get("base_interest_rate"), errors="coerce"),
            "min_initial_margin_fraction": d.get("min_initial_margin_fraction"),
            "collected_at": collected_at,
        })
    df_m = pd.DataFrame(rows)
    df_m["open_interest_usd"] = df_m.open_interest_base * df_m.mark_price
    df_m.to_parquet(f"{OUT}/lighter_markets.parquet", index=False)
    print(f"markets: {len(df_m)}")

    active = df_m[df_m.status == "active"]
    targets = active.nlargest(TOP_N, "daily_quote_volume")
    now_s = int(collected_at.timestamp())
    start_all = now_s - LOOKBACK_DAYS * 86400

    frows = []
    for i, (_, mk) in enumerate(targets.iterrows(), 1):
        t, n0 = start_all, len(frows)
        while t < now_s:
            t2 = min(t + 500 * 3600, now_s)
            d = get("/fundings", {"market_id": int(mk.market_id), "resolution": "1h",
                                  "start_timestamp": t, "end_timestamp": t2,
                                  "count_back": 500})
            for f in d.get("fundings") or []:
                frows.append({"symbol": mk.symbol, "market_id": mk.market_id,
                              "timestamp": f["timestamp"], "rate": f["rate"],
                              "direction": f["direction"], "value": f.get("value")})
            t = t2
        print(f"[{i}/{len(targets)}] {mk.symbol}: {len(frows) - n0} rows")
    df_f = pd.DataFrame(frows)
    df_f["rate"] = pd.to_numeric(df_f["rate"], errors="coerce")
    df_f["rate_signed"] = df_f.rate.where(df_f.direction == "long", -df_f.rate)
    df_f["time"] = pd.to_datetime(df_f["timestamp"], unit="s", utc=True)
    df_f = df_f.drop_duplicates(["symbol", "time"]).sort_values(["symbol", "time"])
    df_f["collected_at"] = collected_at
    df_f.to_parquet(f"{OUT}/lighter_funding_history.parquet", index=False)
    print(f"funding_history: {len(df_f)} rows, {df_f['symbol'].nunique()} symbols")


if __name__ == "__main__":
    main()
