"""Collect dYdX v4 (indexer.dydx.trade) markets + hourly funding history.

Outputs (data/raw/dydx/):
  dydx_markets.parquet          - perpetualMarkets snapshot (OI, 24h volume, next funding)
  dydx_funding_history.parquet  - 90d hourly funding for top markets by 24h volume
"""
import os
import time

import pandas as pd
import requests

BASE = "https://indexer.dydx.trade/v4"
OUT = "/Users/dereklou/Projects/equity-perp/data/raw/dydx"
LOOKBACK_DAYS = 90
TOP_N = 50

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
            time.sleep(float(r.headers.get("Retry-After", 3 * (i + 1))))
            continue
        r.raise_for_status()
        time.sleep(0.1)
        return r.json()
    raise RuntimeError(f"failed: {path} {params}")


def main():
    os.makedirs(OUT, exist_ok=True)
    collected_at = pd.Timestamp.now(tz="UTC")

    mkts = get("/perpetualMarkets", {"limit": 500})["markets"]
    rows = []
    for m in mkts.values():
        rows.append({
            "ticker": m["ticker"], "status": m["status"],
            "oraclePrice": float(m["oraclePrice"]),
            "volume24H": float(m["volume24H"]), "trades24H": m["trades24H"],
            "openInterest_base": float(m["openInterest"]),
            "openInterest_usd": float(m["openInterest"]) * float(m["oraclePrice"]),
            "nextFundingRate": float(m["nextFundingRate"]),
            "collected_at": collected_at,
        })
    df_m = pd.DataFrame(rows)
    df_m.to_parquet(f"{OUT}/dydx_markets.parquet", index=False)
    print(f"markets: {len(df_m)}")

    active = df_m[df_m.status == "ACTIVE"]
    targets = active.nlargest(TOP_N, "volume24H")["ticker"].tolist()
    cutoff = collected_at - pd.Timedelta(days=LOOKBACK_DAYS)

    frows = []
    for i, tkr in enumerate(targets, 1):
        before = None
        n0 = len(frows)
        while True:
            params = {"limit": 100}
            if before:
                params["effectiveBeforeOrAt"] = before
            batch = get(f"/historicalFunding/{tkr}", params)["historicalFunding"]
            if not batch:
                break
            frows.extend(batch)
            oldest = batch[-1]["effectiveAt"]
            if pd.Timestamp(oldest) < cutoff or len(batch) < 100:
                break
            before = (pd.Timestamp(oldest) - pd.Timedelta(milliseconds=1)).isoformat()
        print(f"[{i}/{len(targets)}] {tkr}: {len(frows) - n0} rows")
    df_f = pd.DataFrame(frows)
    df_f["rate"] = pd.to_numeric(df_f["rate"], errors="coerce")
    df_f["price"] = pd.to_numeric(df_f["price"], errors="coerce")
    df_f["effectiveAt"] = pd.to_datetime(df_f["effectiveAt"], utc=True, format="ISO8601")
    df_f = df_f[df_f.effectiveAt >= cutoff].drop_duplicates(["ticker", "effectiveAt"])
    df_f = df_f[["ticker", "effectiveAt", "rate", "price"]].sort_values(["ticker", "effectiveAt"])
    df_f["collected_at"] = collected_at
    df_f.to_parquet(f"{OUT}/dydx_funding_history.parquet", index=False)
    print(f"funding_history: {len(df_f)} rows, {df_f['ticker'].nunique()} tickers")


if __name__ == "__main__":
    main()
