#!/usr/bin/env python
"""Collect Gains Network (gTrade) pair-level market data snapshot.

Source: public backend `https://backend-{chain}.gains.trade/trading-variables`
(chains: arbitrum, base, polygon). One row per (chain, pair). No history
endpoint is exposed by these backends (volume history comes from DefiLlama).

Unit conventions (calibrated against known gTrade parameters, 2026-07):
- Percent values ("P") use 1e10 precision, i.e. raw/1e10 = percent.
- Leverage uses 1e3 precision (1100 -> 1.1x).
- borrowingFees v1 `oi.beforeV10.{long,short,max}` are collateral amounts at
  1e10 precision; `oi.collateral.*` are native collateral decimals (v10-era
  positions); OI in USD = amount * collateralPriceUsd, summed over collaterals.
- Borrowing fee v1: feePerBlock (1e10-precision percent per block) is the MAX
  rate at full OI imbalance; effective rate = feePerBlock * (|netOI|/maxOI)^exp,
  charged to the larger side. Annualized with per-chain avg block times.
- pairInfos.maxLeverages: 0 = use group default; raw 1 (=0.001x) = pair
  effectively suspended/delisted; other values are per-pair overrides (1e3).
- fees[feeIndex].totalPositionSizeFeeP: total open+close fee, 1e10 percent of
  position size. minPositionSizeUsd is 1e2 precision USD.

Output: data/raw/longtail/gains_pairs_snapshot.parquet
Rerunnable; appends nothing (full overwrite each run), `collected_at` in UTC.
"""

import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "longtail"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CHAINS = {
    # chain -> (backend url, approximate average seconds per block)
    "arbitrum": ("https://backend-arbitrum.gains.trade/trading-variables", 0.25),
    "base": ("https://backend-base.gains.trade/trading-variables", 2.0),
    "polygon": ("https://backend-polygon.gains.trade/trading-variables", 2.0),
}

SECONDS_PER_YEAR = 365 * 24 * 3600

ASSET_CLASS = {
    "crypto": "crypto", "altcoins": "crypto", "crypto-degen": "crypto",
    "forex": "forex", "forex-minor": "forex", "forex-exotic": "forex",
    "stocks-1": "stocks", "stocks-2": "stocks", "stocks-3": "stocks",
    "indices": "indices",
    "commodities-1": "commodities", "commodities-2": "commodities",
}

P = 1e10  # standard gains percent precision


def fetch(url: str) -> dict:
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": "research-collector/1.0"})
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))


def collect_chain(chain: str, url: str, block_time_s: float, collected_at: str) -> list[dict]:
    d = fetch(url)
    blocks_per_year = SECONDS_PER_YEAR / block_time_s
    pairs, groups, fees = d["pairs"], d["groups"], d["fees"]
    max_lev_overrides = d["pairInfos"]["maxLeverages"]
    collaterals = [c for c in d["collaterals"] if c.get("isActive")]
    market_open = {
        "forex": d.get("isForexOpen"), "stocks": d.get("isStocksOpen"),
        "indices": d.get("isIndicesOpen"), "commodities": d.get("isCommoditiesOpen"),
        "crypto": True,
    }

    rows = []
    for i, p in enumerate(pairs):
        g = groups[int(p["groupIndex"])]
        acls = ASSET_CLASS.get(g["name"], "other")
        fee = fees[int(p["feeIndex"])]
        ovr = max_lev_overrides[i]

        # aggregate OI across collaterals in USD (v1 borrowing OI ledger holds
        # both pre-v10 (1e10) and v10-era (native decimals) positions)
        oi_long_usd = oi_short_usd = max_oi_usd = 0.0
        borrow = None  # take borrowing params from first collateral (mirrored across collaterals)
        for c in collaterals:
            price = float(c["prices"]["collateralPriceUsd"])
            dec = int(c["collateralConfig"]["decimals"])
            bp = c["borrowingFees"]["v1"]["pairs"][i]
            oi = bp["oi"]
            oi_long_usd += (int(oi["beforeV10"]["long"]) / P + int(oi["collateral"]["oiLongCollateral"]) / 10**dec) * price
            oi_short_usd += (int(oi["beforeV10"]["short"]) / P + int(oi["collateral"]["oiShortCollateral"]) / 10**dec) * price
            max_oi_usd += int(oi["beforeV10"]["max"]) / P * price
            if borrow is None:
                borrow = bp
                funding = c["fundingFees"]["pairParams"][i]
                borrow_v2 = c["borrowingFees"]["v2"]["pairParams"][i]

        fee_per_block = int(borrow["feePerBlock"])
        fee_exp = int(borrow["feeExponent"]) or 1
        bg = borrow.get("groups") or []
        borrow_group_idx = int(bg[-1]["groupIndex"]) if bg else None
        group_fee_per_block = None
        if borrow_group_idx is not None:
            group_fee_per_block = int(
                collaterals[0]["borrowingFees"]["v1"]["groups"][borrow_group_idx]["feePerBlock"]
            )

        pair_max_borrow_apr = fee_per_block / P * blocks_per_year  # percent/yr at full imbalance
        group_max_borrow_apr = (group_fee_per_block / P * blocks_per_year) if group_fee_per_block is not None else None
        util = (oi_long_usd + oi_short_usd) / max_oi_usd if max_oi_usd else None
        imbalance = abs(oi_long_usd - oi_short_usd) / max_oi_usd if max_oi_usd else 0.0
        eff_pair_borrow_apr = pair_max_borrow_apr * imbalance**fee_exp

        rows.append({
            "chain": chain,
            "pair_index": i,
            "pair": f"{p['from']}/{p['to']}",
            "base": p["from"],
            "quote": p["to"],
            "group_index": int(p["groupIndex"]),
            "group_name": g["name"],
            "asset_class": acls,
            "is_suspended": ovr == 1,
            "market_open_now": market_open.get(acls),
            "group_min_leverage": int(g["minLeverage"]) / 1e3,
            "group_max_leverage": int(g["maxLeverage"]) / 1e3,
            "pair_max_leverage_override": (ovr / 1e3) if ovr not in (0, 1) else None,
            "spread_pct": int(p["spreadP"]) / P,
            "fee_index": int(p["feeIndex"]),
            "total_open_close_fee_pct": int(fee["totalPositionSizeFeeP"]) / P,
            "min_position_size_usd": int(fee["minPositionSizeUsd"]) / 1e2,
            "oi_long_usd": oi_long_usd,
            "oi_short_usd": oi_short_usd,
            "max_oi_usd": max_oi_usd,
            "oi_utilization": util,
            "borrow_fee_per_block_raw": fee_per_block,
            "borrow_fee_exponent": fee_exp,
            "pair_max_borrow_apr_pct": pair_max_borrow_apr,
            "pair_effective_borrow_apr_pct": eff_pair_borrow_apr,
            "borrow_group_index": borrow_group_idx,
            "group_max_borrow_apr_pct": group_max_borrow_apr,
            "borrow_v2_rate_per_second_raw": float(borrow_v2["borrowingRatePerSecondP"]),
            "funding_v10_enabled": bool(funding["fundingFeesEnabled"]),
            "funding_skew_coeff_per_year_raw": float(funding["skewCoefficientPerYear"]),
            "backend_last_refreshed": d.get("lastRefreshed"),
            "collected_at": collected_at,
        })
    return rows


def main():
    collected_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for chain, (url, block_time) in CHAINS.items():
        print(f"fetching {chain} ...")
        rows.extend(collect_chain(chain, url, block_time, collected_at))
        time.sleep(1.5)  # polite

    df = pd.DataFrame(rows)
    out = OUT_DIR / "gains_pairs_snapshot.parquet"
    df.to_parquet(out, index=False)
    print(f"wrote {out} rows={len(df)}")
    eq = df[(df.chain == "arbitrum") & df.asset_class.isin(["stocks", "indices", "commodities"])]
    print(eq.groupby(["asset_class", "is_suspended"]).size())


if __name__ == "__main__":
    main()
