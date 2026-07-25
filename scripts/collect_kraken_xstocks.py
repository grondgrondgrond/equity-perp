#!/usr/bin/env python
"""Collect Kraken xStocks (tokenized equities, Backed 'SPV' assets) spot reference data.

Note: tokenized pairs are hidden from the default AssetPairs response; you must pass
aclass_base=tokenized_asset. Pair keys look like AAPLSPVUSD (altname AAPLxUSD,
wsname AAPLx/USD).

Outputs (data/raw/kraken/):
  kraken_xstocks_pairs.parquet       - all tokenized_asset pairs
  kraken_xstocks_ticker.parquet      - current ticker for all tokenized pairs
  kraken_xstocks_daily_ohlc.parquet  - daily OHLC (~720d max) for top N by 24h $ volume
"""
import time

import pandas as pd
import requests

B = "https://api.kraken.com/0/public"
OUT = "/Users/dereklou/Projects/equity-perp/data/raw/kraken"
TOP_N = 15

sess = requests.Session()
sess.headers["User-Agent"] = "equity-perp-research/1.0"


def get(path, params=None, tries=5):
    for i in range(tries):
        try:
            r = sess.get(f"{B}/{path}", params=params, timeout=30)
        except requests.RequestException:
            time.sleep(2 * (i + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(float(r.headers.get("Retry-After", 5 * (i + 1))))
            continue
        j = r.json()
        if j.get("error"):
            raise RuntimeError(f"{path}: {j['error']}")
        time.sleep(0.6)  # kraken public rate limit is strict
        return j["result"]
    raise RuntimeError(f"failed: {path} {params}")


def main():
    collected_at = pd.Timestamp.now(tz="UTC")

    pairs = get("AssetPairs", {"aclass_base": "tokenized_asset"})
    prow = []
    for k, v in pairs.items():
        prow.append({
            "pair": k, "altname": v.get("altname"), "wsname": v.get("wsname"),
            "base": v.get("base"), "quote": v.get("quote"),
            "aclass_base": v.get("aclass_base"), "status": v.get("status"),
            "pair_decimals": v.get("pair_decimals"), "ordermin": v.get("ordermin"),
            "costmin": v.get("costmin"),
            "fee_taker_top": (v.get("fees") or [[None, None]])[0][1],
            "fee_maker_top": (v.get("fees_maker") or [[None, None]])[0][1],
            "leverage_buy_max": max(v.get("leverage_buy") or [0]) or None,
            "collected_at": collected_at,
        })
    df_p = pd.DataFrame(prow)
    df_p.to_parquet(f"{OUT}/kraken_xstocks_pairs.parquet", index=False)
    print(f"pairs: {len(df_p)}")

    trow = []
    # Ticker accepts comma-separated pairs; chunk to be safe.
    # Use ALL unique altnames: on weekends most pairs sit in post_only (24/5 names),
    # only ~12 names trade 24/7 and show status=online.
    names = sorted(df_p.altname.unique())  # Ticker/OHLC want altname (AAPLxUSD) + asset_class param
    for i in range(0, len(names), 20):
        tk = get("Ticker", {"pair": ",".join(names[i:i + 20]), "asset_class": "tokenized_asset"})
        for k, v in tk.items():
            trow.append({
                "pair": k,
                "last": float(v["c"][0]), "bid": float(v["b"][0]), "ask": float(v["a"][0]),
                "vol_24h_base": float(v["v"][1]), "vwap_24h": float(v["p"][1]),
                "trades_24h": int(v["t"][1]), "low_24h": float(v["l"][1]),
                "high_24h": float(v["h"][1]), "open": float(v["o"]),
                "collected_at": collected_at,
            })
    df_t = pd.DataFrame(trow)
    df_t["usd_vol_24h"] = df_t.vol_24h_base * df_t.vwap_24h
    df_t.to_parquet(f"{OUT}/kraken_xstocks_ticker.parquet", index=False)
    print(f"ticker: {len(df_t)}")

    top = df_t.sort_values("usd_vol_24h", ascending=False).head(TOP_N).pair
    orow = []
    for p in top:
        ohlc = get("OHLC", {"pair": p, "interval": 1440, "asset_class": "tokenized_asset"})
        key = [k for k in ohlc if k != "last"][0]
        for c in ohlc[key]:
            orow.append({"pair": p, "time": c[0], "open": float(c[1]), "high": float(c[2]),
                         "low": float(c[3]), "close": float(c[4]), "vwap": float(c[5]),
                         "volume": float(c[6]), "trades": int(c[7])})
        print(f"  ohlc {p}: {len(ohlc[key])} days")
    df_o = pd.DataFrame(orow)
    if len(df_o):
        df_o["time"] = pd.to_datetime(df_o["time"], unit="s", utc=True)
        df_o["collected_at"] = collected_at
    df_o.to_parquet(f"{OUT}/kraken_xstocks_daily_ohlc.parquet", index=False)
    print(f"daily_ohlc: {len(df_o)} rows")


if __name__ == "__main__":
    main()
