#!/usr/bin/env python
"""Collect RWA-perp platform volume trajectory data from DefiLlama.

IMPORTANT CONTEXT (as of 2026-07-11):
  DefiLlama put the derivatives *volume* endpoints behind a paywall sometime
  between 2026-03-01 and 2026-04-02:
      GET https://api.llama.fi/overview/derivatives          -> 402
      GET https://api.llama.fi/summary/derivatives/<slug>    -> 402
  ("Upgrade to the paid API plan at https://defillama.com/subscription")

  This script therefore assembles the best freely-available picture from:
    1. Live  GET /overview/derivatives          (attempted first; used if it ever
       becomes free again / an API key is added)
    2. Wayback Machine: last free 200 snapshot of /overview/derivatives
       (2026-03-01) -- includes totalDataChartBreakdown = per-protocol DAILY
       volume from 2021-02-25 through 2026-03-01.
    3. Wayback Machine: defillama.com/perps page snapshots (Next.js
       __NEXT_DATA__) -- point-in-time protocol tables (24h/7d/30d/1y/allTime,
       open interest, normalized volume) on 2026-05-05, 2026-05-25,
       2026-06-06, 2026-06-18, plus the aggregate daily Perp Volume + OI chart
       through the snapshot date.
    4. Live  GET /overview/open-interest        (free) + per-protocol
       GET /summary/open-interest/<slug>        (free) -- daily OI history up
       to today for every relevant protocol.
    5. Live  GET /overview/normalized-volume + /summary/normalized-volume/<slug>
       (free, only ~19 large perps, history starts 2026-02-03) -- wash-trade
       adjusted volume for hyperliquid-perps / aster-perps / extended-perps /
       paradex-perps etc., used as the freshest volume-like daily series.

Outputs (all parquet, UTC dates) in data/raw/defillama/:
    derivatives_overview.parquet            protocol stats from last free API
                                            snapshot (as-of 2026-03-01)
    perps_page_snapshots.parquet            point-in-time protocol tables from
                                            archived defillama.com/perps pages
    daily_volume_by_protocol.parquet        long (protocol, date, volume_usd)
                                            daily perp volume, 2021-02-25 ->
                                            2026-03-01, all protocols
    daily_volume_chain_breakdown_24h.parquet per-chain 24h volume split per
                                            protocol (as-of overview snapshot)
    total_perp_volume_daily.parquet         market-wide daily perp volume + OI
                                            through 2026-06-18
    open_interest_overview.parquet          live OI overview (today)
    daily_open_interest_by_protocol.parquet live daily OI history per relevant
                                            protocol (through today)
    normalized_volume_overview.parquet      live normalized-volume overview
    daily_normalized_volume_by_protocol.parquet  live daily normalized volume
                                            per covered relevant protocol

Rerunnable; polite rate limiting (>=0.7s between requests).
"""

import gzip
import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

BASE = "https://api.llama.fi"
OUT_DIR = Path("/Users/dereklou/Projects/equity-perp/data/raw/defillama")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SLEEP = 0.7
UA = {"User-Agent": "equity-perp-research/1.0 (contact: derek.dlou@gmail.com)"}

# Keywords for RWA/equity-perp candidate scan (case-insensitive, name+slug)
RWA_KEYWORDS = [
    "ostium", "gains", "avantis", "vest", "xyz", "ventual", "kinetiq",
    "sphere", "dream", "rwa", "stock", "equity", "synth", "forex", "fx",
]
# Named target protocols (plus HIP-3 builder markets)
TARGET_NAME_KEYWORDS = RWA_KEYWORDS + [
    "hyperliquid", "aster", "paradex", "helix", "extended", "hip-3", "hip3",
    "trade.xyz", "tradexyz", "unit",
]


def get(url, **kw):
    time.sleep(SLEEP)
    r = requests.get(url, headers=UA, timeout=60, **kw)
    return r


def get_json(url):
    r = get(url)
    if r.status_code != 200:
        return None, r.status_code, r.text[:120]
    try:
        return r.json(), 200, None
    except Exception:
        return None, 200, "non-json: " + r.text[:120]


def wayback_bytes(url_ts, original):
    """Fetch raw archived bytes (handles double-gzipped payloads)."""
    r = get(f"https://web.archive.org/web/{url_ts}id_/{original}")
    r.raise_for_status()
    data = r.content
    if data[:2] == b"\x1f\x8b":
        data = gzip.GzipFile(fileobj=io.BytesIO(data)).read()
    return data


def wayback_snapshots(original, from_ts="2026", status="200"):
    r = get(
        "https://web.archive.org/cdx/search/cdx",
        params={
            "url": original, "output": "json", "from": from_ts,
            "filter": f"statuscode:{status}", "collapse": "digest",
        },
    )
    rows = r.json()
    return [row[1] for row in rows[1:]] if rows else []


def is_candidate(name, slug):
    s = f"{name} {slug}".lower()
    return any(k in s for k in TARGET_NAME_KEYWORDS)


def ts_to_date(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()


PROTO_STAT_COLS = [
    "name", "displayName", "slug", "defillamaId", "category", "chains",
    "parentProtocol", "total24h", "total48hto24h", "total7d", "total14dto7d",
    "total30d", "total60dto30d", "total1y", "totalAllTime", "total7DaysAgo",
    "total30DaysAgo", "change_1d", "change_7d", "change_1m",
    "change_7dover7d", "change_30dover30d",
]


def protocols_frame(protocols, extra_cols=()):
    rows = []
    for p in protocols:
        row = {c: p.get(c) for c in list(PROTO_STAT_COLS) + list(extra_cols)}
        if isinstance(row.get("chains"), list):
            row["chains"] = ",".join(map(str, row["chains"]))
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    report = {}

    # ------------------------------------------------------------------ #
    # 1. derivatives overview: live first, else last free Wayback snapshot
    # ------------------------------------------------------------------ #
    print("[1] derivatives overview ...")
    overview, code, err = get_json(f"{BASE}/overview/derivatives")
    overview_source = f"live api.llama.fi ({datetime.now(timezone.utc).date()})"
    if overview is None:
        print(f"    live endpoint unavailable (HTTP {code}: {err})")
        snaps = wayback_snapshots("api.llama.fi/overview/derivatives", "2025")
        snaps = sorted(snaps)
        print(f"    wayback 200 snapshots: {snaps}")
        ts = snaps[-1]
        overview = json.loads(wayback_bytes(ts, f"{BASE}/overview/derivatives"))
        overview_source = f"wayback snapshot {ts}"
    print(f"    source: {overview_source}; protocols: {len(overview['protocols'])}")

    df_over = protocols_frame(overview["protocols"])
    df_over["source"] = overview_source
    df_over["retrieved_utc"] = datetime.now(timezone.utc).isoformat()
    df_over.to_parquet(OUT_DIR / "derivatives_overview.parquet", index=False)
    report["derivatives_overview"] = len(df_over)

    # candidates
    cands = df_over[[is_candidate(n, s) for n, s in zip(df_over["name"], df_over["slug"])]]
    print("    candidate protocols in overview:")
    for _, r in cands.sort_values("total30d", ascending=False).iterrows():
        print(f"      {r['name']:32s} slug={r['slug']:28s} 30d={r['total30d']}")

    # ------------------------------------------------------------------ #
    # 2. daily volume by protocol (from overview totalDataChartBreakdown)
    # ------------------------------------------------------------------ #
    print("[2] daily volume by protocol (overview breakdown) ...")
    rows = []
    for ts, bd in overview.get("totalDataChartBreakdown", []):
        d = ts_to_date(ts)
        # breakdown may be flat {protocol: vol} or nested {chain:{protocol: vol}}
        for k, v in bd.items():
            if isinstance(v, dict):
                for proto, vol in v.items():
                    rows.append((proto, d, k, float(vol)))
            else:
                rows.append((k, d, None, float(v)))
    df_daily = pd.DataFrame(rows, columns=["protocol", "date", "chain", "volume_usd"])
    if df_daily["chain"].notna().any():
        df_daily = (
            df_daily.groupby(["protocol", "date"], as_index=False)["volume_usd"].sum()
        )
    else:
        df_daily = df_daily.drop(columns=["chain"])
    df_daily["source"] = overview_source
    df_daily.to_parquet(OUT_DIR / "daily_volume_by_protocol.parquet", index=False)
    report["daily_volume_by_protocol"] = len(df_daily)
    print(f"    rows: {len(df_daily)}; dates {df_daily['date'].min()} -> {df_daily['date'].max()}")

    # per-chain 24h breakdown per protocol (as-of the overview snapshot)
    chain_rows = []
    for p in overview["protocols"]:
        bd = p.get("breakdown24h") or {}
        for chain, sub in bd.items():
            if isinstance(sub, dict):
                for mod, vol in sub.items():
                    chain_rows.append((p["name"], p.get("slug"), chain, mod, vol))
            else:
                chain_rows.append((p["name"], p.get("slug"), chain, None, sub))
    df_chain = pd.DataFrame(
        chain_rows, columns=["protocol", "slug", "chain", "module", "volume_24h_usd"]
    )
    df_chain["source"] = overview_source
    df_chain.to_parquet(OUT_DIR / "daily_volume_chain_breakdown_24h.parquet", index=False)
    report["daily_volume_chain_breakdown_24h"] = len(df_chain)

    # ------------------------------------------------------------------ #
    # 3. archived defillama.com/perps page snapshots (point-in-time tables
    #    + freshest aggregate daily chart)
    # ------------------------------------------------------------------ #
    print("[3] archived defillama.com/perps page snapshots ...")
    page_snaps = sorted(wayback_snapshots("defillama.com/perps", "20260301"))
    print(f"    snapshots: {page_snaps}")
    snap_frames, chart_frames = [], []
    for ts in page_snaps:
        try:
            html = wayback_bytes(ts, "https://defillama.com/perps").decode(
                "utf-8", errors="replace"
            )
            m = re.search(
                r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>',
                html, re.S,
            )
            if not m:
                print(f"    {ts}: no __NEXT_DATA__, skipped")
                continue
            pp = json.loads(m.group(1))["props"]["pageProps"]
            df = pd.DataFrame(pp["protocols"])
            for col in ("chains", "breakdownAliases"):
                if col in df:
                    df[col] = df[col].apply(
                        lambda v: ",".join(map(str, v)) if isinstance(v, list) else v
                    )
            df["snapshot_utc"] = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
            snap_frames.append(df)
            src = pp.get("chartData", {}).get("source", [])
            if src:
                cdf = pd.DataFrame(src)
                cdf["date"] = pd.to_datetime(cdf["timestamp"], unit="ms", utc=True).dt.date.astype(str)
                cdf = cdf.drop(columns=["timestamp"]).rename(
                    columns={"Perp Volume": "perp_volume_usd", "Open Interest": "open_interest_usd"}
                )
                cdf["snapshot_utc"] = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
                chart_frames.append(cdf)
            print(f"    {ts}: {len(df)} protocols")
        except Exception as e:  # noqa: BLE001
            print(f"    {ts}: FAILED ({e})")
    if snap_frames:
        df_snaps = pd.concat(snap_frames, ignore_index=True)
        df_snaps.to_parquet(OUT_DIR / "perps_page_snapshots.parquet", index=False)
        report["perps_page_snapshots"] = len(df_snaps)
    if chart_frames:
        # keep the longest (latest) chart, it supersedes earlier ones
        best = max(chart_frames, key=len)
        best.to_parquet(OUT_DIR / "total_perp_volume_daily.parquet", index=False)
        report["total_perp_volume_daily"] = len(best)

    # ------------------------------------------------------------------ #
    # 4. live open-interest overview + per-protocol daily OI history
    # ------------------------------------------------------------------ #
    print("[4] live open-interest ...")
    oi, code, err = get_json(f"{BASE}/overview/open-interest")
    if oi is None:
        print(f"    open-interest overview unavailable ({code} {err})")
    else:
        df_oi = protocols_frame(oi["protocols"])
        df_oi["retrieved_utc"] = datetime.now(timezone.utc).isoformat()
        df_oi.to_parquet(OUT_DIR / "open_interest_overview.parquet", index=False)
        report["open_interest_overview"] = len(df_oi)
        oi_slugs = [
            p["slug"] for p in oi["protocols"] if is_candidate(p["name"], p["slug"])
        ]
        print(f"    candidate OI slugs: {oi_slugs}")
        oi_rows = []
        for slug in oi_slugs:
            js, code, err = get_json(f"{BASE}/summary/open-interest/{slug}")
            if js is None:
                print(f"    {slug}: HTTP {code} {err}")
                continue
            for ts, val in js.get("totalDataChart") or []:
                oi_rows.append((js.get("name", slug), slug, ts_to_date(ts), float(val)))
            print(f"    {slug}: {len(js.get('totalDataChart') or [])} days OI")
        df_oi_daily = pd.DataFrame(
            oi_rows, columns=["protocol", "slug", "date", "open_interest_usd"]
        )
        df_oi_daily.to_parquet(OUT_DIR / "daily_open_interest_by_protocol.parquet", index=False)
        report["daily_open_interest_by_protocol"] = len(df_oi_daily)

    # ------------------------------------------------------------------ #
    # 5. live normalized-volume (freshest volume-like series, few protocols)
    # ------------------------------------------------------------------ #
    print("[5] live normalized-volume ...")
    nv, code, err = get_json(f"{BASE}/overview/normalized-volume")
    if nv is None:
        print(f"    normalized-volume overview unavailable ({code} {err})")
    else:
        df_nv = protocols_frame(nv["protocols"])
        df_nv["retrieved_utc"] = datetime.now(timezone.utc).isoformat()
        df_nv.to_parquet(OUT_DIR / "normalized_volume_overview.parquet", index=False)
        report["normalized_volume_overview"] = len(df_nv)
        nv_slugs = [
            p["slug"] for p in nv["protocols"] if is_candidate(p["name"], p["slug"])
        ]
        print(f"    candidate NV slugs: {nv_slugs}")
        nv_rows = []
        for slug in nv_slugs:
            js, code, err = get_json(f"{BASE}/summary/normalized-volume/{slug}")
            if js is None:
                print(f"    {slug}: HTTP {code} {err}")
                continue
            for ts, val in js.get("totalDataChart") or []:
                nv_rows.append((js.get("name", slug), slug, ts_to_date(ts), float(val)))
            print(f"    {slug}: {len(js.get('totalDataChart') or [])} days NV")
        df_nv_daily = pd.DataFrame(
            nv_rows, columns=["protocol", "slug", "date", "normalized_volume_usd"]
        )
        df_nv_daily.to_parquet(
            OUT_DIR / "daily_normalized_volume_by_protocol.parquet", index=False
        )
        report["daily_normalized_volume_by_protocol"] = len(df_nv_daily)

    # ------------------------------------------------------------------ #
    # 6. live daily FEES per relevant protocol (free, current through today)
    #    -- best freely available proxy for recent volume trajectory since
    #    perp fee rates are roughly constant per protocol.
    # ------------------------------------------------------------------ #
    print("[6] live daily fees (volume-trajectory proxy) ...")
    fee_slugs = sorted(
        set(
            [p["slug"] for p in overview["protocols"] if is_candidate(p["name"], p["slug"])]
            + ([p["slug"] for p in oi["protocols"] if is_candidate(p["name"], p["slug"])] if oi else [])
        )
    )
    fee_rows = []
    for slug in fee_slugs:
        js, code, err = get_json(f"{BASE}/summary/fees/{slug}")
        if js is None:
            print(f"    {slug}: HTTP {code} {err}")
            continue
        for ts, val in js.get("totalDataChart") or []:
            fee_rows.append((js.get("name", slug), slug, ts_to_date(ts), float(val)))
        print(f"    {slug}: {len(js.get('totalDataChart') or [])} days fees")
    df_fees = pd.DataFrame(fee_rows, columns=["protocol", "slug", "date", "fees_usd"])
    df_fees.to_parquet(OUT_DIR / "daily_fees_by_protocol.parquet", index=False)
    report["daily_fees_by_protocol"] = len(df_fees)

    # ------------------------------------------------------------------ #
    print("\n=== files written ===")
    for k, v in report.items():
        print(f"  {k}.parquet: {v} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
