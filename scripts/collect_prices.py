"""Backtest v1 price/parameter collection (plan: groovy-exploring-dragonfly).

Scope (confirmed 2026-07-24): Tier 1 + US-listed Tier 2.
Underlyings: SK Hynix, MU, SNDK, SMSN, XMR, ETH, SOL, BTC, ZEC(ctx)
             + CRCL, NBIS, HOOD, ORCL, INTC, MRVL, IBM.

Outputs (all UTC, hourly unless noted):
  data/raw/hyperliquid/candles_1h_bt.parquet      main + xyz coins, 200d
  data/raw/lighter/candles_1h.parquet             /api/v1/candles (path per SDK; NOT /candlesticks)
  data/raw/dydx/candles_1h.parquet                ETH/SOL/BTC
  data/raw/spot/coinbase_1h.parquet               ETH/SOL/BTC-USD spot
  data/raw/spot/kucoin_xmr_1h.parquet             XMR-USDT spot (Kraken OHLC only serves ~30d)
  data/raw/equities/equity_1h.parquet             yfinance 1h bars incl 000660.KS, SMSN.IL, KRW=X
  data/raw/equities/equity_daily.parquet          daily bars + dividends/splits columns
  data/raw/rates/sofr_daily.parquet               FRED CSV, no key
  data/raw/{lighter,dydx}/margin_params.parquet   maintenance/initial fractions
  data/raw/hyperliquid/margin_tables.parquet      HL meta margin tables for target coins

Resumable per-file; rerun overwrites. Polite pacing on every API.
"""
import io
import os
import sys
import time

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hl_common import post as hl_post

RAW = "/Users/dereklou/Projects/equity-perp/data/raw"
LOOKBACK_D = 200
MS_H = 3_600_000

HL_COINS = (["BTC", "ETH", "SOL", "XMR", "ZEC"] +
            ["xyz:" + c for c in ["SKHX", "MU", "SNDK", "SMSN", "CRCL", "NBIS",
                                  "HOOD", "ORCL", "INTC", "MRVL", "IBM"]])
LIGHTER_SYMS = ["SKHYNIXUSD", "MU", "SNDK", "CRCL", "ETH", "SOL", "BTC", "XMR"]
DYDX_TICKERS = ["ETH-USD", "SOL-USD", "BTC-USD"]
COINBASE_PRODUCTS = ["ETH-USD", "SOL-USD", "BTC-USD"]
EQUITY_TICKERS = ["MU", "SNDK", "SMSN.IL", "000660.KS", "CRCL", "NBIS", "HOOD",
                  "ORCL", "INTC", "MRVL", "IBM", "KRW=X"]

sess = requests.Session()
sess.headers["User-Agent"] = "equity-perp-research/1.0"


def get(url, params=None, tries=5, sleep=0.15):
    for i in range(tries):
        try:
            r = sess.get(url, params=params, timeout=30)
        except requests.RequestException:
            time.sleep(2 * (i + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(float(r.headers.get("Retry-After", 4 * (i + 1))))
            continue
        r.raise_for_status()
        time.sleep(sleep)
        return r
    raise RuntimeError(f"failed: {url} {params}")


def universe_symbols():
    """(hl_coins, lighter_syms) for all in-universe markets (universe v2)."""
    u = pd.read_parquet(
        "/Users/dereklou/Projects/equity-perp/data/processed/universe_v2.parquet")
    u = u[u.in_universe]
    hl = u[u.venue.isin(["hyperliquid", "hl_xyz"])].symbol.tolist()
    ltr = u[u.venue == "lighter"].symbol.tolist()
    return hl, ltr


def collect_hl(coins=None):
    now = int(time.time() * 1000)
    start = now - LOOKBACK_D * 24 * MS_H
    rows = []
    for coin in coins or HL_COINS:
        time.sleep(0.2)
        recs = hl_post({"type": "candleSnapshot",
                        "req": {"coin": coin, "interval": "1h",
                                "startTime": start, "endTime": now}})
        for k in recs or []:
            rows.append({"coin": coin, "time": k["t"], "open": float(k["o"]),
                         "high": float(k["h"]), "low": float(k["l"]),
                         "close": float(k["c"]), "base_vol": float(k["v"]),
                         "n_trades": k.get("n")})
        print(f"hl {coin}: {len(recs or [])} candles")
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df.to_parquet(f"{RAW}/hyperliquid/candles_1h_bt.parquet", index=False)
    print(f"hl candles: {len(df)}")

    meta = hl_post({"type": "meta"})
    mt_rows = []
    for entry in meta.get("marginTables", []):
        table_id, table = entry
        for tier in table.get("marginTiers", []):
            mt_rows.append({"table_id": table_id,
                            "description": table.get("description"),
                            "lowerBound": float(tier["lowerBound"]),
                            "maxLeverage": tier["maxLeverage"]})
    mt = pd.DataFrame(mt_rows)
    mt.to_parquet(f"{RAW}/hyperliquid/margin_tables.parquet", index=False)
    print(f"hl margin tables: {len(mt)}")


def collect_lighter(syms=None):
    mk = pd.read_parquet(f"{RAW}/lighter/lighter_markets.parquet")
    ids = mk.set_index("symbol")["market_id"].to_dict()
    now = int(time.time())
    start_all = now - LOOKBACK_D * 86400
    rows = []
    for sym in syms or LIGHTER_SYMS:
        if sym not in ids:
            print(f"lighter: {sym} not listed, skipping")
            continue
        t = start_all
        n0 = len(rows)
        while t < now:
            t2 = min(t + 500 * 3600, now)
            d = get("https://mainnet.zklighter.elliot.ai/api/v1/candles",
                    {"market_id": int(ids[sym]), "resolution": "1h",
                     "start_timestamp": t, "end_timestamp": t2,
                     "count_back": 500}).json()
            for k in d.get("c") or []:
                rows.append({"symbol": sym, "time": k["t"], "open": k["o"],
                             "high": k["h"], "low": k["l"], "close": k["c"],
                             "base_vol": k["v"], "quote_vol": k.get("V")})
            t = t2
        print(f"lighter {sym}: {len(rows) - n0} candles")
    df = pd.DataFrame(rows).drop_duplicates(["symbol", "time"])
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df.to_parquet(f"{RAW}/lighter/candles_1h.parquet", index=False)
    print(f"lighter candles: {len(df)}")

    det = get("https://mainnet.zklighter.elliot.ai/api/v1/orderBookDetails").json()
    mp = pd.DataFrame([{
        "symbol": d["symbol"], "market_id": d["market_id"],
        "default_initial_margin_fraction": d.get("default_initial_margin_fraction"),
        "min_initial_margin_fraction": d.get("min_initial_margin_fraction"),
        "maintenance_margin_fraction": d.get("maintenance_margin_fraction"),
        "closeout_margin_fraction": d.get("closeout_margin_fraction"),
        "funding_clamp_small": d.get("funding_clamp_small"),
        "funding_clamp_big": d.get("funding_clamp_big"),
    } for d in det["order_book_details"]])
    mp.to_parquet(f"{RAW}/lighter/margin_params.parquet", index=False)
    print(f"lighter margin params: {len(mp)}")


def collect_dydx():
    B = "https://indexer.dydx.trade/v4"
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=LOOKBACK_D)
    rows = []
    for tkr in DYDX_TICKERS:
        to = None
        n0 = len(rows)
        while True:
            p = {"resolution": "1HOUR", "limit": 100}
            if to:
                p["toISO"] = to
            batch = get(f"{B}/candles/perpetualMarkets/{tkr}", p).json().get("candles", [])
            if not batch:
                break
            rows.extend(dict(b, ticker=tkr) for b in batch)
            oldest = batch[-1]["startedAt"]
            if pd.Timestamp(oldest) < cutoff or len(batch) < 100:
                break
            to = oldest
        print(f"dydx {tkr}: {len(rows) - n0} candles")
    df = pd.DataFrame(rows)
    for c in ["open", "high", "low", "close", "baseTokenVolume", "usdVolume"]:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["time"] = pd.to_datetime(df["startedAt"], utc=True, format="ISO8601")
    df = (df[["ticker", "time", "open", "high", "low", "close", "usdVolume"]]
          .drop_duplicates(["ticker", "time"]).sort_values(["ticker", "time"]))
    df.to_parquet(f"{RAW}/dydx/candles_1h.parquet", index=False)
    print(f"dydx candles: {len(df)}")

    mkts = get(f"{B}/perpetualMarkets", {"limit": 500}).json()["markets"]
    mp = pd.DataFrame([{
        "ticker": m["ticker"],
        "initialMarginFraction": float(m["initialMarginFraction"]),
        "maintenanceMarginFraction": float(m["maintenanceMarginFraction"]),
    } for m in mkts.values()])
    mp.to_parquet(f"{RAW}/dydx/margin_params.parquet", index=False)
    print(f"dydx margin params: {len(mp)}")


def collect_spot():
    os.makedirs(f"{RAW}/spot", exist_ok=True)
    # Coinbase Exchange: 300 hourly candles per request, paginate back
    rows = []
    end = pd.Timestamp.now(tz="UTC").floor("h")
    start_all = end - pd.Timedelta(days=LOOKBACK_D)
    for prod in COINBASE_PRODUCTS:
        t2 = end
        n0 = len(rows)
        while t2 > start_all:
            t1 = max(t2 - pd.Timedelta(hours=300), start_all)
            d = get(f"https://api.exchange.coinbase.com/products/{prod}/candles",
                    {"granularity": 3600, "start": t1.isoformat(), "end": t2.isoformat()}).json()
            for k in d:  # [t, low, high, open, close, vol]
                rows.append({"product": prod, "time": k[0], "low": k[1], "high": k[2],
                             "open": k[3], "close": k[4], "base_vol": k[5]})
            t2 = t1
        print(f"coinbase {prod}: {len(rows) - n0} candles")
    df = pd.DataFrame(rows).drop_duplicates(["product", "time"])
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.to_parquet(f"{RAW}/spot/coinbase_1h.parquet", index=False)
    print(f"coinbase: {len(df)}")

    # KuCoin XMR-USDT: 1500 candles per request
    rows = []
    now_s = int(time.time())
    t2 = now_s
    start_all_s = now_s - LOOKBACK_D * 86400
    while t2 > start_all_s:
        t1 = max(t2 - 1500 * 3600, start_all_s)
        d = get("https://api.kucoin.com/api/v1/market/candles",
                {"symbol": "XMR-USDT", "type": "1hour", "startAt": t1, "endAt": t2}).json()
        for k in d.get("data") or []:  # [t, open, close, high, low, vol, turnover]
            rows.append({"time": int(k[0]), "open": float(k[1]), "close": float(k[2]),
                         "high": float(k[3]), "low": float(k[4]), "base_vol": float(k[5])})
        t2 = t1
    df = pd.DataFrame(rows).drop_duplicates("time")
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.to_parquet(f"{RAW}/spot/kucoin_xmr_1h.parquet", index=False)
    print(f"kucoin XMR: {len(df)}")


def collect_equities():
    import yfinance as yf
    os.makedirs(f"{RAW}/equities", exist_ok=True)
    start = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=LOOKBACK_D)).strftime("%Y-%m-%d")
    h_frames, d_frames = [], []
    for tkr in EQUITY_TICKERS:
        t = yf.Ticker(tkr)
        h = t.history(start=start, interval="1h", auto_adjust=False,
                      actions=False, raise_errors=False)
        if len(h):
            h = h.reset_index().rename(columns=str.lower)
            tcol = "datetime" if "datetime" in h else "date"
            h["time"] = pd.to_datetime(h[tcol], utc=True)
            h["ticker"] = tkr
            h_frames.append(h[["ticker", "time", "open", "high", "low", "close", "volume"]])
        d = t.history(start=start, interval="1d", auto_adjust=False,
                      actions=True, raise_errors=False)
        if len(d):
            d = d.reset_index().rename(columns=str.lower)
            d["time"] = pd.to_datetime(d["date"], utc=True)
            d["ticker"] = tkr
            keep = ["ticker", "time", "open", "high", "low", "close", "volume"]
            for extra in ["dividends", "stock splits"]:
                if extra in d:
                    keep.append(extra)
            d_frames.append(d[keep])
        print(f"equity {tkr}: {len(h)} hourly, {len(d)} daily")
        time.sleep(0.5)
    pd.concat(h_frames, ignore_index=True).to_parquet(
        f"{RAW}/equities/equity_1h.parquet", index=False)
    pd.concat(d_frames, ignore_index=True).to_parquet(
        f"{RAW}/equities/equity_daily.parquet", index=False)
    print("equities saved")


def collect_rates():
    os.makedirs(f"{RAW}/rates", exist_ok=True)
    r = get("https://markets.newyorkfed.org/api/rates/secured/sofr/last/250.json")
    recs = r.json()["refRates"]
    df = pd.DataFrame([{"date": x["effectiveDate"], "sofr": x["percentRate"]}
                       for x in recs])
    df["date"] = pd.to_datetime(df["date"])
    df["sofr"] = pd.to_numeric(df["sofr"], errors="coerce")
    df = df.dropna().sort_values("date")
    df.to_parquet(f"{RAW}/rates/sofr_daily.parquet", index=False)
    print(f"sofr: {len(df)} rows, latest {df.date.max().date()} = {df.sofr.iloc[-1]}")


if __name__ == "__main__":
    parts = set(sys.argv[1:]) or {"hl", "lighter", "dydx", "spot", "equities", "rates"}
    if "universe" in parts:   # universe-v2-driven perp candle collection
        hl_syms, ltr_syms = universe_symbols()
        print(f"universe candles: {len(hl_syms)} HL, {len(ltr_syms)} Lighter")
        collect_hl(hl_syms)
        collect_lighter(ltr_syms)
        parts -= {"hl", "lighter"}
    if "hl" in parts:
        collect_hl()
    if "lighter" in parts:
        collect_lighter()
    if "dydx" in parts:
        collect_dydx()
    if "spot" in parts:
        collect_spot()
    if "equities" in parts:
        collect_equities()
    if "rates" in parts:
        collect_rates()
