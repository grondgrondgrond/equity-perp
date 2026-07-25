#!/usr/bin/env python
"""Collect Ostium (ostium.io) market data.

Sources (all public, no API key):
  - Subgraph (Ormi Labs, endpoint hardcoded in 0xOstium/ostium-python-sdk config.py):
      https://api.subgraph.ormilabs.com/api/public/.../subgraphs/ost-prod/live/gn
    Entities used: pairs (funding/rollover accumulators, OI, caps, params), metaDatas.
    Historical data via time-travel queries: pairs(block: {number: N}).
  - Metadata backend (price feed used by the SDK):
      https://metadata-backend.ostium.io/PricePublish/latest-prices
    Gives bid/mid/ask + isMarketOpen per pair.
  - DefiLlama block resolver https://coins.llama.fi/block/arbitrum/{ts} to map
    UTC-midnight timestamps -> Arbitrum block numbers (cached on disk).

Unit conventions (from 0xOstium/ostium-data-ts formatters.ts + formulae.ts):
  - longOI/shortOI: 1e18, in ASSET units (multiply by price for USD)
  - maxOI, volume, buyVolume, sellVolume: 1e6 (USDC dollars)
  - accFundingLong/Short, accRollover(Long/Short): 1e18; a delta/1e18 is the
    FRACTION of notional paid over the interval (positive = side pays).
    (fee = d_acc * collateral * leverage / 1e18 / 100, collateral 1e6, lev 1e2)
  - curFundingLong/Short, rolloverFeePerBlock: 1e18, fraction of notional per
    L2 block (contract block numbers are in the same space as subgraph heights).
  - leverage fields: x100; makerFeeP/takerFeeP: 1e6 = percent; prices: 1e18.

Outputs (data/raw/ostium/):
  pairs_snapshot.parquet    one row per listed pair, current state
  funding_history.parquet   per pair per UTC day: realized funding + rollover
  daily_volume.parquet      per pair per UTC day: volume (USD)
  pair_daily_raw.parquet    raw daily block snapshots (source of the two above)
  block_cache.json          timestamp->block cache (rerun-friendly)

Rerunnable: python scripts/collect_ostium.py [--start 2025-01-01]
"""
import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

SUBGRAPH_URL = ("https://api.subgraph.ormilabs.com/api/public/"
                "67a599d5-c8d2-4cc4-9c4d-2975a97bc5d8/subgraphs/ost-prod/live/gn")
METADATA_URL = "https://metadata-backend.ostium.io"
LLAMA_BLOCK_URL = "https://coins.llama.fi/block/arbitrum/{ts}"

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "raw" / "ostium"
OUT_DIR.mkdir(parents=True, exist_ok=True)
BLOCK_CACHE_PATH = OUT_DIR / "block_cache.json"

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "equity-perp-research/0.1"

PRECIOUS_METALS = {"XAU", "XAG", "XPT", "XPD"}
GROUP_TO_CLASS = {
    "forex": "fx",
    "indices": "equity_index",
    "stocks": "single_stock",
    "crypto": "crypto",
    "etf": "etf",
    # "commodities" handled specially (precious metals split out)
}

HIST_PAIR_FIELDS = """
    id from to volume buyVolume sellVolume longOI shortOI maxOI
    accFundingLong accFundingShort accRollover accRolloverLong accRolloverShort
    curFundingLong curFundingShort curRollover rolloverFeePerBlock
    maxFundingFeePerBlock lastFundingRate lastTradePrice totalOpenTrades
"""

SNAP_PAIR_FIELDS = HIST_PAIR_FIELDS + """
    feed oracle spreadP maxLeverage overnightMaxLeverage makerFeeP takerFeeP
    usageFeeP vaultFeePercent utilizationThresholdP makerMaxLeverage
    maxFundingFeeVelocity fundingFeeSlope hillInflectionPoint springFactor
    hillPosScale hillNegScale sFactorUpScaleP sFactorDownScaleP
    maxRolloverVolatility maxRolloverFeePerBlock rolloverFeeSlope tradeSizeRef
    totalOpenLimitOrders lastFundingVelocity lastFundingTime lastRolloverTime
    lastFundingBlock lastRolloverBlock isNegativeRolloverAllowed brokerPremium
    group { id name minLeverage maxLeverage maxCollateralP longCollateral shortCollateral }
    fee { minLevPos }
"""


def gql(query: str, retries: int = 6, timeout: int = 90):
    """POST a GraphQL query with retry/backoff. Returns the `data` dict."""
    last_err = None
    for attempt in range(retries):
        try:
            r = SESSION.post(SUBGRAPH_URL, json={"query": query}, timeout=timeout)
            if r.status_code == 200:
                body = r.json()
                if "errors" in body and not body.get("data"):
                    raise RuntimeError(str(body["errors"])[:300])
                return body["data"]
            last_err = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)[:300]
        time.sleep(1.5 * (2 ** attempt))
    raise RuntimeError(f"GraphQL failed after {retries} tries: {last_err}")


def load_block_cache() -> dict:
    if BLOCK_CACHE_PATH.exists():
        return json.loads(BLOCK_CACHE_PATH.read_text())
    return {}


def block_at(ts: int, cache: dict) -> int | None:
    key = str(ts)
    if key in cache:
        return cache[key]
    for attempt in range(5):
        try:
            r = SESSION.get(LLAMA_BLOCK_URL.format(ts=ts), timeout=30)
            if r.status_code == 200:
                h = r.json()["height"]
                cache[key] = h
                return h
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.0 * (2 ** attempt))
    return None


def asset_class(group_name: str, from_sym: str) -> str:
    if group_name == "commodities":
        return "precious_metal" if from_sym in PRECIOUS_METALS else "commodity"
    return GROUP_TO_CLASS.get(group_name, group_name)


def fetch_latest_prices() -> pd.DataFrame:
    r = SESSION.get(f"{METADATA_URL}/PricePublish/latest-prices", timeout=30)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    return df[["from", "to", "bid", "mid", "ask", "isMarketOpen",
               "isDayTradingClosed", "timestampSeconds"]].rename(
        columns={"timestampSeconds": "price_timestamp"})


NUMERIC_RAW = [
    "volume", "buyVolume", "sellVolume", "longOI", "shortOI", "maxOI",
    "accFundingLong", "accFundingShort", "accRollover", "accRolloverLong",
    "accRolloverShort", "curFundingLong", "curFundingShort", "curRollover",
    "rolloverFeePerBlock", "maxFundingFeePerBlock", "lastFundingRate",
    "lastTradePrice", "totalOpenTrades",
]


def pairs_at_block(block: int | None) -> list[dict]:
    block_arg = f", block: {{number: {block}}}" if block else ""
    q = f"{{ pairs(first: 1000{block_arg}) {{ {HIST_PAIR_FIELDS} }} }}"
    return gql(q)["pairs"]


CHECKPOINT_PATH = OUT_DIR / "pair_daily_checkpoint.parquet"


def collect_daily_history(start_date: str) -> pd.DataFrame:
    """Daily UTC-midnight snapshots of all pairs via time-travel queries.

    Resumable: rows are checkpointed periodically; already-fetched dates skipped.
    """
    cache = load_block_cache()
    start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    dates = []
    d = start
    while d <= now:
        dates.append(d)
        d += timedelta(days=1)

    rows = []
    done_dates = set()
    if CHECKPOINT_PATH.exists():
        prev = pd.read_parquet(CHECKPOINT_PATH)
        prev = prev[prev["snapshot_date"] != "NOW"]
        rows = prev.to_dict("records")
        done_dates = set(prev["snapshot_date"])
        print(f"  resuming: {len(done_dates)} dates already checkpointed")

    n_llama = 0
    for i, dt in enumerate(dates):
        if dt.date().isoformat() in done_dates:
            continue
        ts = int(dt.timestamp())
        blk = block_at(ts, cache)
        n_llama += 1
        if n_llama % 25 == 0:
            BLOCK_CACHE_PATH.write_text(json.dumps(cache))
            pd.DataFrame(rows).to_parquet(CHECKPOINT_PATH, index=False)
        if blk is None:
            print(f"  {dt.date()} no block found, skipping")
            continue
        try:
            pairs = pairs_at_block(blk)
        except RuntimeError as e:
            print(f"  {dt.date()} block {blk}: {e}")
            continue
        for p in pairs:
            row = {"snapshot_ts": ts, "snapshot_date": dt.date().isoformat(),
                   "block": blk, "pair_id": int(p["id"]),
                   "from_sym": p["from"], "to_sym": p["to"]}
            for f in NUMERIC_RAW:
                row[f] = float(p[f]) if p.get(f) is not None else None
            rows.append(row)
        if i % 25 == 0:
            print(f"  {dt.date()} block {blk}: {len(pairs)} pairs")
        time.sleep(0.12)  # polite rate limiting
    BLOCK_CACHE_PATH.write_text(json.dumps(cache))
    pd.DataFrame(rows).to_parquet(CHECKPOINT_PATH, index=False)

    # final "now" snapshot to close the last partial day
    meta = gql("{ _meta { block { number timestamp } } }")["_meta"]["block"]
    pairs = pairs_at_block(None)
    for p in pairs:
        row = {"snapshot_ts": int(meta["timestamp"]),
               "snapshot_date": "NOW", "block": int(meta["number"]),
               "pair_id": int(p["id"]), "from_sym": p["from"], "to_sym": p["to"]}
        for f in NUMERIC_RAW:
            row[f] = float(p[f]) if p.get(f) is not None else None
        rows.append(row)

    df = pd.DataFrame(rows)
    df["collected_at"] = pd.Timestamp.now(tz="UTC")
    return df


def build_derived(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Diff consecutive snapshots into per-day funding + volume tables."""
    raw = raw.sort_values(["pair_id", "snapshot_ts"]).copy()
    g = raw.groupby("pair_id")
    diffs = {
        "d_volume": "volume", "d_buyVolume": "buyVolume",
        "d_sellVolume": "sellVolume", "d_accFundingLong": "accFundingLong",
        "d_accFundingShort": "accFundingShort", "d_accRollover": "accRollover",
        "d_accRolloverLong": "accRolloverLong",
        "d_accRolloverShort": "accRolloverShort",
    }
    for new, src in diffs.items():
        raw[new] = g[src].diff().shift(-1)  # delta from this snapshot to next
    raw["d_seconds"] = g["snapshot_ts"].diff().shift(-1)
    raw["d_blocks"] = g["block"].diff().shift(-1)

    day = raw[raw["snapshot_date"] != "NOW"].dropna(subset=["d_seconds"]).copy()
    day["partial_day"] = day["d_seconds"] < 86000

    funding = pd.DataFrame({
        "date": day["snapshot_date"], "pair_id": day["pair_id"],
        "from_sym": day["from_sym"], "to_sym": day["to_sym"],
        "interval_seconds": day["d_seconds"], "partial_day": day["partial_day"],
        "block_start": day["block"].astype("int64"),
        # realized fee fractions of notional over the day (+ = side pays)
        "funding_long_frac": day["d_accFundingLong"] / 1e18,
        "funding_short_frac": day["d_accFundingShort"] / 1e18,
        "rollover_frac": day["d_accRollover"] / 1e18,
        "rollover_long_frac": day["d_accRolloverLong"] / 1e18,
        "rollover_short_frac": day["d_accRolloverShort"] / 1e18,
        # instantaneous per-block rates at snapshot (fraction of notional/block)
        "cur_funding_long_per_block": day["curFundingLong"] / 1e18,
        "cur_funding_short_per_block": day["curFundingShort"] / 1e18,
        "rollover_fee_per_block": day["rolloverFeePerBlock"] / 1e18,
        "last_funding_rate_per_block": day["lastFundingRate"] / 1e18,
        "blocks_in_interval": day["d_blocks"],
        # OI at snapshot (asset units) + price for USD conversion
        "long_oi_asset": day["longOI"] / 1e18,
        "short_oi_asset": day["shortOI"] / 1e18,
        "last_trade_price": day["lastTradePrice"] / 1e18,
        "max_oi_usd": day["maxOI"] / 1e6,
    })
    funding["collected_at"] = pd.Timestamp.now(tz="UTC")

    volume = pd.DataFrame({
        "date": day["snapshot_date"], "pair_id": day["pair_id"],
        "from_sym": day["from_sym"], "to_sym": day["to_sym"],
        "partial_day": day["partial_day"],
        "volume_usd": day["d_volume"] / 1e6,
        "buy_volume_usd": day["d_buyVolume"] / 1e6,
        "sell_volume_usd": day["d_sellVolume"] / 1e6,
        "cum_volume_usd": day["volume"] / 1e6,
    })
    volume["collected_at"] = pd.Timestamp.now(tz="UTC")
    return funding, volume


def collect_pairs_snapshot(raw_hist: pd.DataFrame) -> pd.DataFrame:
    """Current full snapshot of every pair, merged with live prices + 24h vol."""
    q = f"{{ pairs(first: 1000) {{ {SNAP_PAIR_FIELDS} }} }}"
    pairs = gql(q)["pairs"]
    prices = fetch_latest_prices()

    # 24h volume: cumulative volume now minus at (now - 24h)
    cache = load_block_cache()
    blk_24h = block_at(int(time.time()) - 86400, cache)
    BLOCK_CACHE_PATH.write_text(json.dumps(cache))
    vol_24h_ago = {}
    if blk_24h:
        for p in pairs_at_block(blk_24h):
            vol_24h_ago[int(p["id"])] = float(p["volume"])

    rows = []
    for p in pairs:
        pid = int(p["id"])
        grp = p["group"]
        px = float(p["lastTradePrice"]) / 1e18
        long_oi = float(p["longOI"]) / 1e18
        short_oi = float(p["shortOI"]) / 1e18
        max_oi_usd = float(p["maxOI"]) / 1e6
        max_lev = float(p["maxLeverage"]) / 100 or float(grp["maxLeverage"]) / 100
        rows.append({
            "pair_id": pid, "from_sym": p["from"], "to_sym": p["to"],
            "group_name": grp["name"],
            "asset_class": asset_class(grp["name"], p["from"]),
            "feed": p["feed"], "oracle": p["oracle"],
            "last_trade_price": px,
            "long_oi_asset": long_oi, "short_oi_asset": short_oi,
            "long_oi_usd": long_oi * px, "short_oi_usd": short_oi * px,
            "max_oi_usd": max_oi_usd,
            "oi_utilization": ((long_oi + short_oi) * px / max_oi_usd)
                              if max_oi_usd else None,
            "min_leverage": float(grp["minLeverage"]) / 100,
            "max_leverage": max_lev,
            "overnight_max_leverage": float(p["overnightMaxLeverage"]) / 100 or None,
            "maker_max_leverage": float(p["makerMaxLeverage"]) / 100,
            "group_max_leverage": float(grp["maxLeverage"]) / 100,
            "maker_fee_pct": float(p["makerFeeP"]) / 1e6,
            "taker_fee_pct": float(p["takerFeeP"]) / 1e6,
            "usage_fee_pct": float(p["usageFeeP"]) / 1e6,
            "min_lev_pos_usd": float(p["fee"]["minLevPos"]) / 1e6,
            "spread_p_raw": float(p["spreadP"]),
            "cur_funding_long_per_block": float(p["curFundingLong"]) / 1e18,
            "cur_funding_short_per_block": float(p["curFundingShort"]) / 1e18,
            "last_funding_rate_per_block": float(p["lastFundingRate"]) / 1e18,
            "max_funding_fee_per_block": float(p["maxFundingFeePerBlock"]) / 1e18,
            "rollover_fee_per_block": float(p["rolloverFeePerBlock"]) / 1e18,
            "max_rollover_fee_per_block": float(p["maxRolloverFeePerBlock"]) / 1e18,
            "acc_funding_long": float(p["accFundingLong"]) / 1e18,
            "acc_funding_short": float(p["accFundingShort"]) / 1e18,
            "acc_rollover": float(p["accRollover"]) / 1e18,
            "acc_rollover_long": float(p["accRolloverLong"]) / 1e18,
            "acc_rollover_short": float(p["accRolloverShort"]) / 1e18,
            "is_negative_rollover_allowed": p["isNegativeRolloverAllowed"],
            "funding_fee_slope": float(p["fundingFeeSlope"]),
            "hill_inflection_point": float(p["hillInflectionPoint"]),
            "hill_pos_scale": float(p["hillPosScale"]),
            "hill_neg_scale": float(p["hillNegScale"]),
            "spring_factor": float(p["springFactor"]),
            "s_factor_up_scale_p": float(p["sFactorUpScaleP"]),
            "s_factor_down_scale_p": float(p["sFactorDownScaleP"]),
            "utilization_threshold_p": float(p["utilizationThresholdP"]),
            "trade_size_ref": float(p["tradeSizeRef"]),
            "last_funding_time": int(p["lastFundingTime"]),
            "last_rollover_time": int(p["lastRolloverTime"]),
            "total_open_trades": int(p["totalOpenTrades"]),
            "total_open_limit_orders": int(p["totalOpenLimitOrders"]),
            "cum_volume_usd": float(p["volume"]) / 1e6,
            "volume_24h_usd": (float(p["volume"]) - vol_24h_ago[pid]) / 1e6
                              if pid in vol_24h_ago else None,
            "group_max_collateral_p": float(grp["maxCollateralP"]) / 100,
            "group_long_collateral": float(grp["longCollateral"]) / 1e6,
            "group_short_collateral": float(grp["shortCollateral"]) / 1e6,
        })
    df = pd.DataFrame(rows).sort_values("pair_id")

    df = df.merge(prices, how="left",
                  left_on=["from_sym", "to_sym"], right_on=["from", "to"])
    df = df.drop(columns=["from", "to"]).rename(columns={
        "bid": "feed_bid", "mid": "feed_mid", "ask": "feed_ask",
        "isMarketOpen": "is_market_open",
        "isDayTradingClosed": "is_day_trading_closed"})

    # annualize per-block rates with empirical blocks/day from history
    bl = raw_hist.groupby("snapshot_date")["block"].first().sort_index()
    blocks_per_day = float(bl.diff().tail(30).median())
    df["blocks_per_day_est"] = blocks_per_day
    for col in ["cur_funding_long", "cur_funding_short", "rollover_fee"]:
        df[f"{col}_apr_pct"] = df[f"{col}_per_block"] * blocks_per_day * 365 * 100

    df["collected_at"] = pd.Timestamp.now(tz="UTC")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-01-01",
                    help="first UTC date for daily history")
    args = ap.parse_args()

    print(f"[1/3] Daily history snapshots since {args.start} ...")
    raw = collect_daily_history(args.start)
    raw.to_parquet(OUT_DIR / "pair_daily_raw.parquet", index=False)
    print(f"  raw snapshots: {len(raw)} rows -> pair_daily_raw.parquet")

    print("[2/3] Deriving funding_history + daily_volume ...")
    funding, volume = build_derived(raw)
    funding.to_parquet(OUT_DIR / "funding_history.parquet", index=False)
    volume.to_parquet(OUT_DIR / "daily_volume.parquet", index=False)
    print(f"  funding_history: {len(funding)} rows; daily_volume: {len(volume)} rows")

    print("[3/3] Current pairs snapshot ...")
    snap = collect_pairs_snapshot(raw)
    snap.to_parquet(OUT_DIR / "pairs_snapshot.parquet", index=False)
    print(f"  pairs_snapshot: {len(snap)} rows")

    meta = gql("{ metaDatas { totalVolume totalTrades totalUsers totalOpenTrades } }")
    print("platform meta:", meta["metaDatas"][0])


if __name__ == "__main__":
    main()
