#!/usr/bin/env python
"""Collect RWA perp data from Paradex, Extended, and Helix/Injective.

Paradex  (https://api.prod.paradex.trade/v1):
  - RWA perps carry tags=["RWA"]. Funding data is emitted every 5s, no server-side
    downsampling, so we point-sample via end_at (page_size=1) on a grid (>=4h).
  paradex_markets.parquet, paradex_summary.parquet,
  paradex_funding_history.parquet, paradex_klines_1h.parquet

Extended (https://api.starknet.extended.exchange/api/v1  — note starknet subdomain;
  api.extended.exchange 404s). TradFi markets have category="TradFi". Hourly funding
  via /info/{market}/funding?startTime&endTime; daily candles via
  /info/candles/{market}/trades?interval=P1D.
  extended_markets.parquet, extended_funding_history.parquet, extended_daily_candles.parquet

Helix / Injective iAssets (https://sentry.exchange.grpc-web.injective.network):
  derivative/v1/markets + derivative/v1/fundingRates (hourly, skip/limit pagination).
  helix_markets.parquet, helix_funding_history.parquet

All timestamps UTC, `collected_at` on every table. Rerunnable; overwrites outputs.
"""
import time

import pandas as pd
import requests

OUT = "/Users/dereklou/Projects/equity-perp/data/raw/longtail"
LOOKBACK_DAYS = 185

sess = requests.Session()
sess.headers["User-Agent"] = "equity-perp-research/1.0"


def get(url, params=None, tries=5, sleep=0.1):
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


# --------------------------------------------------------------------------- Paradex
def collect_paradex(collected_at, do_funding=True, do_klines=True):
    B = "https://api.prod.paradex.trade/v1"
    mkts = get(f"{B}/markets")["results"]
    perps = [m for m in mkts if m.get("asset_kind") == "PERP"]
    rows = []
    for m in perps:
        rows.append({
            "symbol": m["symbol"], "base_currency": m["base_currency"],
            "quote_currency": m["quote_currency"], "settlement_currency": m["settlement_currency"],
            "open_at": pd.Timestamp(m.get("open_at", 0), unit="ms", tz="UTC"),
            "tags": ",".join(m.get("tags") or []),
            "is_rwa": "RWA" in (m.get("tags") or []),
            "funding_period_hours": m.get("funding_period_hours"),
            "max_funding_rate": m.get("max_funding_rate"),
            "position_limit": m.get("position_limit"),
            "imf_base": (m.get("delta1_cross_margin_params") or {}).get("imf_base"),
            "api_taker_fee": ((m.get("fee_config") or {}).get("api_fee") or {}).get("taker_fee", {}).get("fee"),
            "collected_at": collected_at,
        })
    df_m = pd.DataFrame(rows)
    df_m.to_parquet(f"{OUT}/paradex_markets.parquet", index=False)
    rwa = df_m[df_m.is_rwa]
    print(f"paradex markets: {len(df_m)} perps, {len(rwa)} RWA")

    summ = get(f"{B}/markets/summary", {"market": "ALL"})["results"]
    df_s = pd.DataFrame([s for s in summ if s["symbol"].endswith("-PERP")])
    for c in ["mark_price", "last_traded_price", "bid", "ask", "volume_24h", "total_volume",
              "underlying_price", "open_interest", "funding_rate", "price_change_rate_24h"]:
        if c in df_s:
            df_s[c] = pd.to_numeric(df_s[c], errors="coerce")
    df_s["collected_at"] = collected_at
    df_s.to_parquet(f"{OUT}/paradex_summary.parquet", index=False)
    print(f"paradex summary: {len(df_s)} rows")

    # funding: point-sample via end_at on >=4h grid, <=400 samples per market
    now_ms = int(collected_at.timestamp() * 1000)
    frows = []
    for _, mk in rwa.iterrows() if do_funding else []:
        start = max(int(mk.open_at.timestamp() * 1000),
                    now_ms - LOOKBACK_DAYS * 86400_000)
        step = max(4 * 3600_000, (now_ms - start) // 400)
        t = start + step
        while t <= now_ms:
            res = get(f"{B}/funding/data",
                      {"market": mk.symbol, "page_size": 1, "end_at": t}, sleep=0.06)["results"]
            if res:
                r = res[0]
                frows.append({"market": mk.symbol,
                              "funding_rate": r.get("funding_rate"),
                              "funding_rate_8h": r.get("funding_rate_8h"),
                              "funding_premium": r.get("funding_premium"),
                              "funding_index": r.get("funding_index"),
                              "funding_period_hours": r.get("funding_period_hours"),
                              "created_at": r.get("created_at")})
            t += step
        print(f"  paradex funding {mk.symbol}: cum {len(frows)}")
    if do_funding:
        df_f = pd.DataFrame(frows)
        if len(df_f):
            for c in ["funding_rate", "funding_rate_8h", "funding_premium", "funding_index"]:
                df_f[c] = pd.to_numeric(df_f[c], errors="coerce")
            df_f["created_at"] = pd.to_datetime(df_f["created_at"], unit="ms", utc=True)
            df_f = df_f.drop_duplicates(["market", "created_at"])
            df_f["collected_at"] = collected_at
        df_f.to_parquet(f"{OUT}/paradex_funding_history.parquet", index=False)
        print(f"paradex funding_history: {len(df_f)} rows")

    if not do_klines:
        return
    # hourly klines from open_at (RWA perps are young; sparse candles only on trades)
    # endpoint 400s on ranges much over a month -> chunk into 30d windows
    krows = []
    for _, mk in rwa.iterrows():
        start = max(int(mk.open_at.timestamp() * 1000), now_ms - LOOKBACK_DAYS * 86400_000)
        t = start
        while t < now_ms:
            t2 = min(t + 30 * 86400_000, now_ms)
            try:
                kl = get(f"{B}/markets/klines",
                         {"symbol": mk.symbol, "resolution": 60, "start_at": t, "end_at": t2})
            except (requests.HTTPError, RuntimeError) as e:
                print(f"  klines {mk.symbol} chunk skipped: {e}")
                t = t2
                continue
            data = kl.get("results", kl) if isinstance(kl, dict) else kl
            for k in data or []:
                krows.append({"symbol": mk.symbol, "openTime": k[0], "open": k[1], "high": k[2],
                              "low": k[3], "close": k[4], "volume": k[5]})
            t = t2
    df_k = pd.DataFrame(krows)
    if len(df_k):
        df_k["openTime"] = pd.to_datetime(df_k["openTime"], unit="ms", utc=True)
        df_k["collected_at"] = collected_at
    df_k.to_parquet(f"{OUT}/paradex_klines_1h.parquet", index=False)
    print(f"paradex klines_1h: {len(df_k)} rows")


# --------------------------------------------------------------------------- Extended
def collect_extended(collected_at):
    B = "https://api.starknet.extended.exchange/api/v1"
    mkts = get(f"{B}/info/markets")["data"]
    rows = []
    for m in mkts:
        st = m.get("marketStats") or {}
        tc = m.get("tradingConfig") or {}
        rows.append({
            "name": m["name"], "uiName": m.get("uiName"), "category": m.get("category"),
            "subCategory": m.get("subCategory"), "assetName": m.get("assetName"),
            "active": m.get("active"), "status": m.get("status"),
            "isOffHours": m.get("isOffHours"), "tradingHours": m.get("tradingHours"),
            "dailyVolume": st.get("dailyVolume"), "lastPrice": st.get("lastPrice"),
            "markPrice": st.get("markPrice"), "indexPrice": st.get("indexPrice"),
            "fundingRate": st.get("fundingRate"), "openInterest": st.get("openInterest"),
            "maxLeverage": tc.get("maxLeverage"),
            "collected_at": collected_at,
        })
    df_m = pd.DataFrame(rows)
    for c in ["dailyVolume", "lastPrice", "markPrice", "indexPrice", "fundingRate",
              "openInterest", "maxLeverage"]:
        df_m[c] = pd.to_numeric(df_m[c], errors="coerce")
    df_m.to_parquet(f"{OUT}/extended_markets.parquet", index=False)
    tradfi = df_m[(df_m.category == "TradFi") & df_m.active & (df_m.status == "ACTIVE")]
    print(f"extended markets: {len(df_m)}, TradFi active: {len(tradfi)}")

    now_ms = int(collected_at.timestamp() * 1000)
    start_all = now_ms - LOOKBACK_DAYS * 86400_000
    chunk = 14 * 86400_000  # 14d of hourly funding = 336 rows per call
    frows = []
    for name in tradfi.name:
        t = start_all
        while t < now_ms:
            d = get(f"{B}/info/{name}/funding",
                    {"startTime": t, "endTime": min(t + chunk, now_ms), "limit": 1000},
                    sleep=0.08)
            frows.extend(d.get("data") or [])
            t += chunk
        print(f"  extended funding {name}: cum {len(frows)}")
    df_f = pd.DataFrame(frows)
    if len(df_f):
        df_f = df_f.rename(columns={"m": "market", "f": "fundingRate", "T": "time"})
        df_f["fundingRate"] = pd.to_numeric(df_f["fundingRate"], errors="coerce")
        df_f["time"] = pd.to_datetime(df_f["time"], unit="ms", utc=True)
        df_f = df_f.drop_duplicates(["market", "time"])
        df_f["collected_at"] = collected_at
    df_f.to_parquet(f"{OUT}/extended_funding_history.parquet", index=False)
    print(f"extended funding_history: {len(df_f)} rows")

    crows = []
    for name in tradfi.name:
        d = get(f"{B}/info/candles/{name}/trades",
                {"interval": "P1D", "limit": 400, "endTime": now_ms})
        for k in d.get("data") or []:
            crows.append(dict(market=name, open=k["o"], high=k["h"], low=k["l"],
                              close=k["c"], volume=k["v"], time=k["T"]))
    df_c = pd.DataFrame(crows)
    if len(df_c):
        for c in ["open", "high", "low", "close", "volume"]:
            df_c[c] = pd.to_numeric(df_c[c], errors="coerce")
        df_c["time"] = pd.to_datetime(df_c["time"], unit="ms", utc=True)
        df_c["collected_at"] = collected_at
    df_c.to_parquet(f"{OUT}/extended_daily_candles.parquet", index=False)
    print(f"extended daily_candles: {len(df_c)} rows")


# --------------------------------------------------------------------------- Helix / Injective
HELIX_TRADFI_BASES = {
    "MSFT", "AMZN", "META", "COIN", "NVDA", "HOOD", "GOOGL", "TSLA", "AAPL", "PLTR",
    "MSTR", "CRCL", "INTC", "AMD", "NFLX", "TSM", "SPX", "XAU", "XAG", "XAUT",
    "EURUSD", "USDJPY", "GOLD", "SILVER",
}


def collect_helix(collected_at):
    B = "https://sentry.exchange.grpc-web.injective.network/api/exchange/derivative/v1"
    mkts = get(f"{B}/markets")["markets"]
    rows = []
    for m in mkts:
        base = m["ticker"].split("/")[0]
        pmi = m.get("perpetualMarketInfo") or {}
        pmf = m.get("perpetualMarketFunding") or {}
        rows.append({
            "marketId": m["marketId"], "ticker": m["ticker"], "status": m.get("marketStatus"),
            "is_tradfi": base in HELIX_TRADFI_BASES,
            "oracleType": m.get("oracleType"),
            "makerFeeRate": m.get("makerFeeRate"), "takerFeeRate": m.get("takerFeeRate"),
            "initialMarginRatio": m.get("initialMarginRatio"),
            "maintenanceMarginRatio": m.get("maintenanceMarginRatio"),
            "fundingInterval_s": pmi.get("fundingInterval"),
            "hourlyFundingRateCap": pmi.get("hourlyFundingRateCap"),
            "hourlyInterestRate": pmi.get("hourlyInterestRate"),
            "lastFundingRate": pmf.get("lastFundingRate"),
            "cumulativeFunding": pmf.get("cumulativeFunding"),
            "collected_at": collected_at,
        })
    df_m = pd.DataFrame(rows)
    df_m.to_parquet(f"{OUT}/helix_markets.parquet", index=False)
    tradfi = df_m[df_m.is_tradfi & (df_m.status == "active")]
    print(f"helix markets: {len(df_m)}, tradfi: {len(tradfi)}")

    cutoff_ms = int((collected_at - pd.Timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)
    frows = []
    for _, mk in tradfi.iterrows():
        skip = 0
        while True:
            d = get(f"{B}/fundingRates",
                    {"marketId": mk.marketId, "limit": 100, "skip": skip}, sleep=0.06)
            batch = d.get("fundingRates") or []
            if not batch:
                break
            for b in batch:
                frows.append({"marketId": mk.marketId, "ticker": mk.ticker,
                              "rate": b["rate"], "timestamp": b["timestamp"]})
            if batch[-1]["timestamp"] < cutoff_ms or len(batch) < 100:
                break
            skip += 100
            if skip > 5000:  # hourly*185d=4440
                break
        print(f"  helix funding {mk.ticker}: cum {len(frows)}")
    df_f = pd.DataFrame(frows)
    if len(df_f):
        df_f["rate"] = pd.to_numeric(df_f["rate"], errors="coerce")
        df_f["timestamp"] = pd.to_datetime(df_f["timestamp"], unit="ms", utc=True)
        df_f = df_f[df_f.timestamp >= pd.Timestamp(cutoff_ms, unit="ms", tz="UTC")]
        df_f["collected_at"] = collected_at
    df_f.to_parquet(f"{OUT}/helix_funding_history.parquet", index=False)
    print(f"helix funding_history: {len(df_f)} rows")


if __name__ == "__main__":
    import sys
    parts = set(sys.argv[1:]) or {"paradex", "extended", "helix"}
    ts = pd.Timestamp.now(tz="UTC")
    if "paradex" in parts:
        collect_paradex(ts)
    elif "paradex_klines" in parts:  # resume without redoing funding point-sampling
        collect_paradex(ts, do_funding=False, do_klines=True)
    if "extended" in parts:
        collect_extended(ts)
    if "helix" in parts:
        collect_helix(ts)
