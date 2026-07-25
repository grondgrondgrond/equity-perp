"""Aster expansion: full-universe (crypto incl.) tickers + funding history.

Complements collect_aster.py (RWA-only). Outputs (data/raw/longtail/):
  aster_all_ticker24h.parquet       - 24h ticker, ALL symbols
  aster_all_premium_index.parquet   - mark/index/funding snapshot, ALL symbols
  aster_crypto_funding_history.parquet - 90d funding for top crypto perps by quote volume
"""
import time

import pandas as pd
import requests

BASE = "https://fapi.asterdex.com"
OUT = "/Users/dereklou/Projects/equity-perp/data/raw/longtail"
LOOKBACK_DAYS = 90
TOP_N = 60
RWA_TAGS = {"STOCK", "ETF", "Commodities"}

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
            time.sleep(float(r.headers.get("Retry-After", 5 * (i + 1))))
            continue
        r.raise_for_status()
        time.sleep(0.12)
        return r.json()
    raise RuntimeError(f"failed: {path} {params}")


def main():
    collected_at = pd.Timestamp.now(tz="UTC")

    info = get("/fapi/v1/exchangeInfo")
    sym_meta = {}
    for s in info["symbols"]:
        subs = set(s.get("underlyingSubType") or [])
        sym_meta[s["symbol"]] = {
            "is_rwa": bool(subs & RWA_TAGS),
            "status": s.get("status"),
            "contractType": s.get("contractType"),
        }

    tk = pd.DataFrame(get("/fapi/v1/ticker/24hr"))
    for c in ["lastPrice", "volume", "quoteVolume", "priceChangePercent"]:
        tk[c] = pd.to_numeric(tk[c], errors="coerce")
    tk["is_rwa"] = tk.symbol.map(lambda s: sym_meta.get(s, {}).get("is_rwa", False))
    tk["status"] = tk.symbol.map(lambda s: sym_meta.get(s, {}).get("status"))
    tk["collected_at"] = collected_at
    tk.to_parquet(f"{OUT}/aster_all_ticker24h.parquet", index=False)

    pi = pd.DataFrame(get("/fapi/v1/premiumIndex"))
    for c in ["markPrice", "indexPrice", "lastFundingRate", "interestRate"]:
        if c in pi:
            pi[c] = pd.to_numeric(pi[c], errors="coerce")
    pi["collected_at"] = collected_at
    pi.to_parquet(f"{OUT}/aster_all_premium_index.parquet", index=False)
    print(f"tickers: {len(tk)}, premium: {len(pi)}")

    crypto = tk[(~tk.is_rwa) & (tk.status == "TRADING")]
    targets = crypto.nlargest(TOP_N, "quoteVolume")["symbol"].tolist()
    start_ms = int((collected_at - pd.Timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)

    frows = []
    for i, sym in enumerate(targets, 1):
        cursor, n0 = start_ms, len(frows)
        while True:
            batch = get("/fapi/v1/fundingRate",
                        {"symbol": sym, "startTime": cursor, "limit": 1000})
            if not batch:
                break
            frows.extend(batch)
            if len(batch) < 1000:
                break
            cursor = batch[-1]["fundingTime"] + 1
        print(f"[{i}/{len(targets)}] {sym}: {len(frows) - n0} rows")
    df_f = pd.DataFrame(frows)
    df_f["fundingRate"] = pd.to_numeric(df_f["fundingRate"], errors="coerce")
    df_f["fundingTime"] = pd.to_datetime(df_f["fundingTime"], unit="ms", utc=True)
    df_f["collected_at"] = collected_at
    df_f.to_parquet(f"{OUT}/aster_crypto_funding_history.parquet", index=False)
    print(f"crypto funding_history: {len(df_f)} rows, {df_f['symbol'].nunique()} symbols")


if __name__ == "__main__":
    main()
