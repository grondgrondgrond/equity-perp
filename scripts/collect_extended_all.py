"""Extended expansion: markets snapshot + 90d hourly funding for ALL active markets
(crypto + TradFi), superseding the TradFi-only pull in collect_misc_venues.py.

Outputs (data/raw/longtail/):
  extended_markets_latest.parquet
  extended_funding_all.parquet
"""
import time

import pandas as pd
import requests

B = "https://api.starknet.extended.exchange/api/v1"
OUT = "/Users/dereklou/Projects/equity-perp/data/raw/longtail"
LOOKBACK_DAYS = 90

sess = requests.Session()
sess.headers["User-Agent"] = "equity-perp-research/1.0"


def get(url, params=None, tries=5, sleep=0.08):
    for i in range(tries):
        try:
            r = sess.get(url, params=params, timeout=30)
        except requests.RequestException:
            time.sleep(2 * (i + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(float(r.headers.get("Retry-After", 5 * (i + 1))))
            continue
        r.raise_for_status()
        time.sleep(sleep)
        return r.json()
    raise RuntimeError(f"failed: {url} {params}")


def main():
    collected_at = pd.Timestamp.now(tz="UTC")
    mkts = get(f"{B}/info/markets")["data"]
    rows = []
    for m in mkts:
        st = m.get("marketStats") or {}
        tc = m.get("tradingConfig") or {}
        rows.append({
            "name": m["name"], "category": m.get("category"),
            "assetName": m.get("assetName"), "active": m.get("active"),
            "status": m.get("status"),
            "dailyVolume": pd.to_numeric(st.get("dailyVolume"), errors="coerce"),
            "markPrice": pd.to_numeric(st.get("markPrice"), errors="coerce"),
            "fundingRate": pd.to_numeric(st.get("fundingRate"), errors="coerce"),
            "openInterest": pd.to_numeric(st.get("openInterest"), errors="coerce"),
            "maxLeverage": pd.to_numeric(tc.get("maxLeverage"), errors="coerce"),
            "collected_at": collected_at,
        })
    df_m = pd.DataFrame(rows)
    df_m.to_parquet(f"{OUT}/extended_markets_latest.parquet", index=False)
    active = df_m[df_m.active & (df_m.status == "ACTIVE")]
    print(f"markets: {len(df_m)}, active: {len(active)}")

    now_ms = int(collected_at.timestamp() * 1000)
    start_all = now_ms - LOOKBACK_DAYS * 86400_000
    chunk = 14 * 86400_000
    frows = []
    for i, name in enumerate(active.name, 1):
        t, n0 = start_all, len(frows)
        while t < now_ms:
            d = get(f"{B}/info/{name}/funding",
                    {"startTime": t, "endTime": min(t + chunk, now_ms), "limit": 1000})
            frows.extend(d.get("data") or [])
            t += chunk
        print(f"[{i}/{len(active)}] {name}: {len(frows) - n0} rows")
    df_f = pd.DataFrame(frows).rename(columns={"m": "market", "f": "fundingRate", "T": "time"})
    df_f["fundingRate"] = pd.to_numeric(df_f["fundingRate"], errors="coerce")
    df_f["time"] = pd.to_datetime(df_f["time"], unit="ms", utc=True)
    df_f = df_f.drop_duplicates(["market", "time"]).sort_values(["market", "time"])
    df_f["collected_at"] = collected_at
    df_f.to_parquet(f"{OUT}/extended_funding_all.parquet", index=False)
    print(f"funding_all: {len(df_f)} rows, {df_f['market'].nunique()} markets")


if __name__ == "__main__":
    main()
