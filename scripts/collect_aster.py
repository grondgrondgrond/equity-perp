#!/usr/bin/env python
"""Collect RWA (stock/ETF/commodity) perp data from Aster DEX (Binance-style fapi).

Outputs (data/raw/longtail/):
  aster_symbols.parquet          - full exchangeInfo symbol table w/ is_rwa flag
  aster_ticker24h.parquet        - 24h ticker snapshot for RWA symbols
  aster_premium_index.parquet    - mark/index/funding snapshot for RWA symbols
  aster_funding_history.parquet  - funding history ~180 days back, paginated
  aster_daily_klines.parquet     - 1d klines since 2025-06-01

Rerunnable; overwrites parquets. Polite: ~0.12s between requests, retry on 429/5xx.
"""
import time
import datetime as dt

import pandas as pd
import requests

BASE = "https://fapi.asterdex.com"
OUT = "/Users/dereklou/Projects/equity-perp/data/raw/longtail"
RWA_TAGS = {"STOCK", "ETF", "Commodities"}
FUNDING_LOOKBACK_DAYS = 185
KLINES_START = dt.datetime(2025, 6, 1, tzinfo=dt.timezone.utc)

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
            wait = float(r.headers.get("Retry-After", 5 * (i + 1)))
            print(f"  {r.status_code} on {path}, sleeping {wait}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        time.sleep(0.12)
        return r.json()
    raise RuntimeError(f"failed after {tries} tries: {path} {params}")


def now_utc():
    return pd.Timestamp.now(tz="UTC")


def main():
    collected_at = now_utc()

    # ---- exchangeInfo ----
    info = get("/fapi/v1/exchangeInfo")
    rows = []
    for s in info["symbols"]:
        subs = s.get("underlyingSubType") or []
        rows.append({
            "symbol": s["symbol"],
            "status": s.get("status"),
            "contractType": s.get("contractType"),
            "baseAsset": s.get("baseAsset"),
            "quoteAsset": s.get("quoteAsset"),
            "underlyingType": s.get("underlyingType"),
            "underlyingSubType": ",".join(subs),
            "is_rwa": bool(set(subs) & RWA_TAGS),
            "is_prelaunch": "pre-launch" in subs,
            "onboardDate": pd.Timestamp(s.get("onboardDate", 0), unit="ms", tz="UTC"),
            "maintMarginPercent": float(s.get("maintMarginPercent", "nan")),
            "requiredMarginPercent": float(s.get("requiredMarginPercent", "nan")),
            "pricePrecision": s.get("pricePrecision"),
            "collected_at": collected_at,
        })
    df_sym = pd.DataFrame(rows)
    df_sym.to_parquet(f"{OUT}/aster_symbols.parquet", index=False)
    rwa = df_sym[df_sym.is_rwa & df_sym.status.isin(["TRADING", "SETTLING"])]
    rwa_syms = sorted(rwa.symbol)
    print(f"exchangeInfo: {len(df_sym)} symbols, {len(rwa_syms)} RWA active")

    # ---- 24h tickers (single call for all, then filter) ----
    tk = get("/fapi/v1/ticker/24hr")
    df_tk = pd.DataFrame(tk)
    df_tk = df_tk[df_tk.symbol.isin(rwa_syms)].copy()
    for c in ["priceChangePercent", "lastPrice", "weightedAvgPrice", "volume", "quoteVolume", "highPrice", "lowPrice"]:
        if c in df_tk:
            df_tk[c] = pd.to_numeric(df_tk[c], errors="coerce")
    df_tk["collected_at"] = collected_at
    df_tk.to_parquet(f"{OUT}/aster_ticker24h.parquet", index=False)
    print(f"ticker24h: {len(df_tk)} rows")

    # ---- premium index snapshot (all symbols in one call) ----
    pi = get("/fapi/v1/premiumIndex")
    df_pi = pd.DataFrame(pi)
    df_pi = df_pi[df_pi.symbol.isin(rwa_syms)].copy()
    for c in ["markPrice", "indexPrice", "estimatedSettlePrice", "lastFundingRate", "interestRate"]:
        if c in df_pi:
            df_pi[c] = pd.to_numeric(df_pi[c], errors="coerce")
    for c in ["nextFundingTime", "time"]:
        if c in df_pi:
            df_pi[c] = pd.to_datetime(df_pi[c], unit="ms", utc=True)
    df_pi["collected_at"] = collected_at
    df_pi.to_parquet(f"{OUT}/aster_premium_index.parquet", index=False)
    print(f"premiumIndex: {len(df_pi)} rows")

    # ---- funding history, paginated back ~180d ----
    start_ms = int((collected_at - pd.Timedelta(days=FUNDING_LOOKBACK_DAYS)).timestamp() * 1000)
    fund_rows = []
    for i, sym in enumerate(rwa_syms):
        cursor = start_ms
        while True:
            batch = get("/fapi/v1/fundingRate", {"symbol": sym, "startTime": cursor, "limit": 1000})
            if not batch:
                break
            fund_rows.extend(batch)
            if len(batch) < 1000:
                break
            cursor = batch[-1]["fundingTime"] + 1
        if (i + 1) % 20 == 0:
            print(f"  funding {i+1}/{len(rwa_syms)}")
    df_f = pd.DataFrame(fund_rows)
    if len(df_f):
        df_f["fundingRate"] = pd.to_numeric(df_f["fundingRate"], errors="coerce")
        if "markPrice" in df_f:
            df_f["markPrice"] = pd.to_numeric(df_f["markPrice"], errors="coerce")
        df_f["fundingTime"] = pd.to_datetime(df_f["fundingTime"], unit="ms", utc=True)
        df_f["collected_at"] = collected_at
    df_f.to_parquet(f"{OUT}/aster_funding_history.parquet", index=False)
    print(f"funding_history: {len(df_f)} rows")

    # ---- daily klines since 2025-06-01 ----
    kstart = int(KLINES_START.timestamp() * 1000)
    kcols = ["openTime", "open", "high", "low", "close", "volume", "closeTime",
             "quoteVolume", "trades", "takerBuyBase", "takerBuyQuote", "ignore"]
    kl_rows = []
    for i, sym in enumerate(rwa_syms):
        kl = get("/fapi/v1/klines", {"symbol": sym, "interval": "1d", "startTime": kstart, "limit": 1000})
        for k in kl:
            kl_rows.append(dict(zip(kcols, k), symbol=sym))
        if (i + 1) % 20 == 0:
            print(f"  klines {i+1}/{len(rwa_syms)}")
    df_k = pd.DataFrame(kl_rows)
    if len(df_k):
        for c in ["open", "high", "low", "close", "volume", "quoteVolume", "takerBuyBase", "takerBuyQuote"]:
            df_k[c] = pd.to_numeric(df_k[c], errors="coerce")
        df_k["openTime"] = pd.to_datetime(df_k["openTime"], unit="ms", utc=True)
        df_k["closeTime"] = pd.to_datetime(df_k["closeTime"], unit="ms", utc=True)
        df_k = df_k.drop(columns=["ignore"])
        df_k["collected_at"] = collected_at
    df_k.to_parquet(f"{OUT}/aster_daily_klines.parquet", index=False)
    print(f"daily_klines: {len(df_k)} rows")


if __name__ == "__main__":
    main()
