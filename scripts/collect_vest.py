#!/usr/bin/env python
"""Collect RWA (stock/forex) perp data from Vest Markets (formerly vest.exchange).

API base: https://server-prod.hz.vestmarkets.com/v2  (old serverprod.vest.exchange is dead)
Required header: xrestservermm: restserver0

Outputs (data/raw/longtail/):
  vest_symbols.parquet          - exchangeInfo symbol table (asset: stock/crypto/forex)
  vest_ticker24h.parquet        - 24h tickers, all symbols
  vest_ticker_latest.parquet    - mark/index/1h funding/cumFunding snapshot, all symbols
  vest_funding_history.parquet  - hourly funding, ~180d, TRADING stock+forex symbols
  vest_daily_klines.parquet     - 1d klines since 2025-06-01, TRADING stock+forex symbols

Funding on Vest is quoted as a 1-hour rate (oneHrFundingRate), sampled hourly here
(raw endpoint is minute-granularity; interval=1h downsamples server-side).
"""
import time

import pandas as pd
import requests

BASE = "https://server-prod.hz.vestmarkets.com/v2"
OUT = "/Users/dereklou/Projects/equity-perp/data/raw/longtail"
FUNDING_LOOKBACK_DAYS = 185
KLINES_START_MS = int(pd.Timestamp("2025-06-01", tz="UTC").timestamp() * 1000)

sess = requests.Session()
sess.headers.update({"xrestservermm": "restserver0",
                     "User-Agent": "equity-perp-research/1.0"})


def get(path, params=None, tries=5):
    for i in range(tries):
        try:
            r = sess.get(BASE + path, params=params, timeout=30)
        except requests.RequestException:
            time.sleep(2 * (i + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(float(r.headers.get("Retry-After", 5 * (i + 1))))
            continue
        r.raise_for_status()
        time.sleep(0.15)
        return r.json()
    raise RuntimeError(f"failed: {path} {params}")


def main():
    collected_at = pd.Timestamp.now(tz="UTC")

    info = get("/exchangeInfo")
    df_sym = pd.DataFrame(info["symbols"])
    df_sym["collected_at"] = collected_at
    df_sym.to_parquet(f"{OUT}/vest_symbols.parquet", index=False)
    rwa = df_sym[(df_sym.asset.isin(["stock", "forex"])) & (df_sym.tradingStatus == "TRADING")]
    rwa_syms = sorted(rwa.symbol)
    print(f"symbols: {len(df_sym)} total, {len(rwa_syms)} TRADING stock/forex")

    tk = get("/ticker/24hr")["tickers"]
    df_tk = pd.DataFrame(tk)
    for c in ["openPrice", "closePrice", "highPrice", "lowPrice", "quoteVolume", "volume",
              "priceChange", "priceChangePercent"]:
        if c in df_tk:
            df_tk[c] = pd.to_numeric(df_tk[c], errors="coerce")
    for c in ["openTime", "closeTime"]:
        if c in df_tk:
            df_tk[c] = pd.to_datetime(df_tk[c], unit="ms", utc=True)
    df_tk["collected_at"] = collected_at
    df_tk.to_parquet(f"{OUT}/vest_ticker24h.parquet", index=False)
    print(f"ticker24h: {len(df_tk)} rows")

    lt = get("/ticker/latest")["tickers"]
    df_lt = pd.DataFrame(lt)
    for c in ["markPrice", "indexPrice", "imbalance", "oneHrFundingRate", "cumFunding"]:
        if c in df_lt:
            df_lt[c] = pd.to_numeric(df_lt[c], errors="coerce")
    df_lt["collected_at"] = collected_at
    df_lt.to_parquet(f"{OUT}/vest_ticker_latest.parquet", index=False)
    print(f"ticker_latest: {len(df_lt)} rows")

    # hourly funding history, paginate back via endTime
    start_ms = int((collected_at - pd.Timedelta(days=FUNDING_LOOKBACK_DAYS)).timestamp() * 1000)
    frows = []
    for i, sym in enumerate(rwa_syms):
        end = None
        while True:
            params = {"symbol": sym, "interval": "1h", "limit": 1000}
            if end:
                params["endTime"] = end
            batch = get("/funding/history", params)
            if not batch:
                break
            frows.extend(batch)
            oldest = min(b["time"] for b in batch)
            if oldest <= start_ms or len(batch) < 1000:
                break
            end = oldest - 1
        if (i + 1) % 20 == 0:
            print(f"  funding {i+1}/{len(rwa_syms)}")
    df_f = pd.DataFrame(frows)
    if len(df_f):
        df_f["oneHrFundingRate"] = pd.to_numeric(df_f["oneHrFundingRate"], errors="coerce")
        df_f["time"] = pd.to_datetime(df_f["time"], unit="ms", utc=True)
        df_f = df_f[df_f.time >= pd.Timestamp(start_ms, unit="ms", tz="UTC")]
        df_f = df_f.drop_duplicates(["symbol", "time"])
        df_f["collected_at"] = collected_at
    df_f.to_parquet(f"{OUT}/vest_funding_history.parquet", index=False)
    print(f"funding_history: {len(df_f)} rows")

    # daily klines
    kcols = ["openTime", "open", "high", "low", "close", "volume", "closeTime", "quoteVolume", "trades"]
    krows = []
    for i, sym in enumerate(rwa_syms):
        kl = get("/klines", {"symbol": sym, "interval": "1d",
                             "startTime": KLINES_START_MS, "limit": 1000})
        data = kl.get("data", kl) if isinstance(kl, dict) else kl
        for k in data or []:
            krows.append(dict(zip(kcols, k[:9]), symbol=sym))
        if (i + 1) % 20 == 0:
            print(f"  klines {i+1}/{len(rwa_syms)}")
    df_k = pd.DataFrame(krows)
    if len(df_k):
        for c in ["open", "high", "low", "close", "volume", "quoteVolume"]:
            df_k[c] = pd.to_numeric(df_k[c], errors="coerce")
        df_k["openTime"] = pd.to_datetime(df_k["openTime"], unit="ms", utc=True)
        df_k["closeTime"] = pd.to_datetime(df_k["closeTime"], unit="ms", utc=True)
        df_k["collected_at"] = collected_at
    df_k.to_parquet(f"{OUT}/vest_daily_klines.parquet", index=False)
    print(f"daily_klines: {len(df_k)} rows")


if __name__ == "__main__":
    main()
