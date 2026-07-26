"""Options snapshot collector (exploratory step-4 study — see plan; NOT in METHODOLOGY).

Dated full-chain snapshots from two free sources + the one free IV history series:
  CBOE delayed quotes  -> data/raw/options/{YYYY-MM-DD}/cboe_{TKR}_{tag}.parquet
  Deribit book summary -> data/raw/options/{YYYY-MM-DD}/deribit_{CCY}_{tag}.parquet
  Deribit DVOL history -> data/raw/options/dvol.parquet

tag = HHMMZ of the run, or 'eod' for the canonical 22:00Z daily run that
options_rv.py reads by default.

Sampling policy (Derek, 2026-07-25): hourly, per-source market hours —
  Deribit: every run (24/7; weekend crypto snapshots are the point).
  CBOE: only during US RTH (weekday ~9:35-16:10 ET) or on the eod run.
  DVOL: once per day (idempotent full-history overwrite).
Full chains, no pruning at collection — all filtering happens in options_rv.py.

Usage: collect_options.py [cboe|deribit|dvol|eod|force ...]   (default: auto by clock)
  'eod'   tag this run as the canonical daily snapshot (cron at 22:00 UTC)
  'force' ignore market-hours gating (manual runs)
Runs on Derek's Mac and on the headless collector box (repo-root-derived paths).
"""
import datetime as dt
import os
import re
import sys
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect_prices import get

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_BASE = f"{ROOT}/data/raw/options"

# base_name (universe v2) -> CBOE ticker; None = no accessible US chain (documented)
US_CHAIN_MAP = {
    # US single stocks / ADRs with listed chains
    "AAPL": "AAPL", "NVDA": "NVDA", "GOOGL": "GOOGL", "TSLA": "TSLA",
    "MSTR": "MSTR", "PLTR": "PLTR", "COIN": "COIN", "AMD": "AMD",
    "NFLX": "NFLX", "META": "META", "AMZN": "AMZN", "AVGO": "AVGO",
    "DELL": "DELL", "MSFT": "MSFT", "SNDK": "SNDK", "INTC": "INTC",
    "ORCL": "ORCL", "HOOD": "HOOD", "CRWV": "CRWV", "CRCL": "CRCL",
    "BE": "BE", "IBM": "IBM", "MU": "MU", "AMAT": "AMAT", "NOW": "NOW",
    "LITE": "LITE", "HIMS": "HIMS", "RKLB": "RKLB", "MRVL": "MRVL",
    "NBIS": "NBIS", "GME": "GME", "BB": "BB", "ARM": "ARM",
    "TSM": "TSM", "BABA": "BABA", "ASML": "ASML", "NOK": "NOK",
    "EWY": "EWY", "XLE": "XLE",
    # no accessible US chain — proxy or nothing (documented as None)
    "STRC": None,          # preferred stock, no chain
    "XYZ100": None,        # index basket -> QQQ proxy in PROXY_ETFS
    "SP500": None,         # -> SPY
    "JP225": None,         # -> EWJ
    "QNT": None, "BOT": None,          # thematic baskets
    "GOLD": None, "XAU": None,         # -> GLD
    "SILVER": None, "XAG": None,       # -> SLV
    "PLATINUM": None, "COPPER": None,
    "CL": None, "WTI": None,           # -> USO
    "BRENTOIL": None,                  # -> BNO
    "NATGAS": None,
    "JPY": None, "EUR": None,          # FX, no equity chain
    "SKHX": None, "SKHYNIX": None, "SMSN": None, "KIOXIA": None,
    "HYUNDAI": None, "MINIMAX": None,  # foreign listings, inaccessible
    "SPCX": None, "CBRS": None, "ZHIPU": None, "DRAM": None,  # no underlying
    "BTC": None, "ETH": None, "SOL": None,   # -> Deribit
    "HYPE": None, "LIT": None,               # no listed options
}
PROXY_ETFS = ["EWY", "EWJ", "GLD", "SLV", "USO", "BNO", "QQQ", "SPY"]
DERIBIT_CCYS = ["BTC", "ETH"]              # inverse (coin-settled): currency=CCY
DERIBIT_USDC_ROOTS = ["SOL_USDC", "HYPE_USDC"]  # linear USDC-settled: currency=USDC

OCC_RE = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")


def cboe_tickers() -> list[str]:
    tks = sorted({t for t in US_CHAIN_MAP.values() if t} | set(PROXY_ETFS))
    # warn (don't drop) if universe has base names missing from the map
    uni_path = f"{ROOT}/data/processed/universe_v2.parquet"
    try:
        import universe
        u = pd.read_parquet(uni_path)
        bases = {universe.base_name(s) for s in u[u.in_universe].symbol}
        missing = bases - set(US_CHAIN_MAP)
        if missing:
            print(f"WARN: universe base names missing from US_CHAIN_MAP: {sorted(missing)}")
    except Exception:
        pass  # headless box: static map is the source of truth
    return tks


def collect_cboe(day_dir: str, tag: str):
    ts = pd.Timestamp.now(tz="UTC")
    queue = [(t, 0.6) for t in cboe_tickers()]
    failed = []
    while queue:
        tkr, slp = queue.pop(0)
        try:
            r = get(f"https://cdn.cboe.com/api/global/delayed_quotes/options/{tkr}.json",
                    sleep=slp)
        except RuntimeError as e:
            if slp < 3:                      # one slower retry pass at the end
                queue.append((tkr, 3.0))
            else:
                failed.append(tkr)
                print(f"cboe {tkr}: FAILED {e}")
            continue
        js = r.json()
        data = js.get("data", {})
        # RAW-FIRST: every per-option field verbatim; parsed columns are ADDITIVE
        df = pd.DataFrame(data.get("options", []))
        if df.empty:
            print(f"cboe {tkr}: empty chain")
            continue
        parsed = df["option"].str.extract(OCC_RE)
        parsed.columns = ["p_root", "p_ymd", "p_right", "p_strike_raw"]
        df["p_root"] = parsed.p_root
        df["p_expiry"] = pd.to_datetime("20" + parsed.p_ymd.str[:2] + "-" +
                                        parsed.p_ymd.str[2:4] + "-" + parsed.p_ymd.str[4:6],
                                        errors="coerce")
        df["p_right"] = parsed.p_right
        df["p_strike"] = pd.to_numeric(parsed.p_strike_raw, errors="coerce") / 1000.0
        # every top-level scalar of the payload, verbatim, prefixed u_ / payload_
        for k, v in data.items():
            if not isinstance(v, (list, dict)):
                df[f"u_{k}"] = v
        df["payload_timestamp"] = js.get("timestamp")   # CBOE quote-generation time
        df["underlying"] = tkr
        df["collected_at"] = ts
        df.to_parquet(f"{day_dir}/cboe_{tkr}_{tag}.parquet", index=False)
        print(f"cboe {tkr}: {len(df)} contracts, "
              f"spot={data.get('current_price')}")
    if failed:
        print(f"cboe: PERMANENT FAILURES this run: {failed}")


DERIBIT_RE = re.compile(r"^([A-Z_]+)-(\d{1,2})([A-Z]{3})(\d{2})-(\d+(?:d\d+)?)-([CP])$")
_MON = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def _parse_deribit(result, roots_filter=None):
    """RAW-FIRST: every API field verbatim; parsed p_* columns are ADDITIVE.
    Price units: coin-settled instruments quote bid/ask/mark in UNDERLYING units,
    USDC-settled in USDC — stored as-is; conversion happens in analysis only."""
    rows = []
    for o in result:
        m = DERIBIT_RE.match(o.get("instrument_name", ""))
        if not m:
            continue
        root, dd, mon, yy, strike, right = m.groups()
        if roots_filter and root not in roots_filter:
            continue
        rec = dict(o)   # verbatim payload
        rec["p_root"] = root
        rec["p_expiry"] = pd.Timestamp(2000 + int(yy), _MON[mon], int(dd))
        rec["p_right"] = right
        rec["p_strike"] = float(strike.replace("d", "."))
        rows.append(rec)
    return rows


def collect_deribit(day_dir: str, tag: str):
    ts = pd.Timestamp.now(tz="UTC")
    for ccy in DERIBIT_CCYS:
        r = get("https://www.deribit.com/api/v2/public/get_book_summary_by_currency",
                {"currency": ccy, "kind": "option"}, sleep=0.3)
        df = pd.DataFrame(_parse_deribit(r.json().get("result", [])))
        df["currency"] = ccy
        df["settlement"] = "coin"
        df["collected_at"] = ts
        df.to_parquet(f"{day_dir}/deribit_{ccy}_{tag}.parquet", index=False)
        print(f"deribit {ccy}: {len(df)} instruments")
    # linear USDC-settled complex (SOL, HYPE — yes, listed HYPE options exist)
    r = get("https://www.deribit.com/api/v2/public/get_book_summary_by_currency",
            {"currency": "USDC", "kind": "option"}, sleep=0.3)
    result = r.json().get("result", [])
    for root in DERIBIT_USDC_ROOTS:
        df = pd.DataFrame(_parse_deribit(result, roots_filter={root}))
        ccy = root.split("_")[0]
        df["currency"] = ccy
        df["settlement"] = "usdc"
        df["collected_at"] = ts
        df.to_parquet(f"{day_dir}/deribit_{ccy}_{tag}.parquet", index=False)
        print(f"deribit {ccy} (USDC-linear): {len(df)} instruments")


def collect_dvol():
    ts = pd.Timestamp.now(tz="UTC")
    frames = []
    end = int(ts.timestamp() * 1000)
    year_ms = 365 * 86_400_000
    for ccy in ["BTC", "ETH"]:
        chunks = []
        t0 = 1609459200000  # 2021-01-01; API caps ~1000 rows/request -> yearly chunks
        while t0 < end:
            t1 = min(t0 + year_ms, end)
            r = get("https://www.deribit.com/api/v2/public/get_volatility_index_data",
                    {"currency": ccy, "start_timestamp": t0,
                     "end_timestamp": t1, "resolution": "1D"}, sleep=0.3)
            chunks.extend(r.json().get("result", {}).get("data", []))
            t0 = t1
        df = pd.DataFrame(chunks, columns=["t", "open", "high", "low", "close"])
        df = df.drop_duplicates("t")
        df["time"] = pd.to_datetime(df["t"], unit="ms", utc=True)
        df["currency"] = ccy
        frames.append(df.drop(columns="t"))
    out = pd.concat(frames, ignore_index=True)
    out["collected_at"] = ts
    out.to_parquet(f"{OUT_BASE}/dvol.parquet", index=False)
    print(f"dvol: {len(out)} rows, {out.time.min().date()} -> {out.time.max().date()}")


def us_rth_now() -> bool:
    now_et = dt.datetime.now(ZoneInfo("America/New_York"))
    if now_et.weekday() >= 5:
        return False
    t = now_et.time()
    return dt.time(9, 35) <= t <= dt.time(16, 10)


def main():
    args = set(sys.argv[1:])
    now = pd.Timestamp.now(tz="UTC")
    eod = "eod" in args
    force = "force" in args
    tag = "eod" if eod else now.strftime("%H%M") + "Z"
    parts = args & {"cboe", "deribit", "dvol"}

    day_dir = f"{OUT_BASE}/{now.strftime('%Y-%m-%d')}"
    os.makedirs(day_dir, exist_ok=True)

    if not parts:  # auto mode: per-source market hours
        parts = {"deribit"}
        if eod or force or us_rth_now():
            parts.add("cboe")
        if not os.path.exists(f"{OUT_BASE}/dvol.parquet") or eod:
            parts.add("dvol")

    if "cboe" in parts:
        if force or eod or us_rth_now() or "cboe" in args:
            collect_cboe(day_dir, tag)
        else:
            print("cboe: outside US RTH, skipped (use 'force')")
    if "deribit" in parts:
        collect_deribit(day_dir, tag)
    if "dvol" in parts:
        collect_dvol()


if __name__ == "__main__":
    main()
