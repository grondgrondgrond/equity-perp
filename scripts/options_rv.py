"""Options-vs-funding RV analysis (exploratory step-4 study — NOT in METHODOLOGY).

Two structures per in-universe perp market with an options chain:
  1. SYNTHETIC FORWARD: implied carry from put-call parity vs operative funding.
     edge_synth = funding(1m ann) - pessimistic implied carry - perp entry tc (ann).
     Spot-hedge alternative reported alongside: funding - (SOFR + IBKR_SPREAD - q).
  2. CONVEX HEDGE: ~75-delta call at ~30d; theta drag annualized per unit
     delta-notional; edge_convex = funding - drag. Tail truncation qualitative.

Assumptions (stated): flat SOFR discounting; T = calendar days/365; trailing-12m
dividend yield proxies forward; American early-exercise premium ~0 near-ATM
short-dated; CBOE quotes are 15-min delayed (eod snapshot = frozen close state).
Flags, not filters: OI-sensitivity printed at OI >= {0,100,1000}; earnings/div-in-
window flagged; half-spreads reported. Nothing silently dropped.

Usage: options_rv.py [--date YYYY-MM-DD]   (default: latest dated dir, eod-preferred)
Output: data/processed/options_rv.parquet + printed tables.
"""
import glob
import os
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect_options import US_CHAIN_MAP
from forecast_funding import operative_forecast
import universe as uni_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPT = f"{ROOT}/data/raw/options"
OUT = f"{ROOT}/data/processed"
HY = 24 * 365
IBKR_SPREAD = 0.015
BUCKETS = {"~30d": 30, "~90d": 90}
DERIBIT_NAMES = {"BTC", "ETH", "SOL", "HYPE"}


def latest_day_dir(date_arg=None):
    if date_arg:
        return f"{OPT}/{date_arg}"
    days = sorted(d for d in os.listdir(OPT) if re.match(r"\d{4}-\d{2}-\d{2}$", d))
    return f"{OPT}/{days[-1]}"


def load_chain(day_dir, prefix):
    """Latest snapshot for a ticker: prefer *_eod, else newest tag."""
    files = sorted(glob.glob(f"{day_dir}/{prefix}_*.parquet"))
    if not files:
        return None
    eod = [f for f in files if f.endswith("_eod.parquet")]
    return pd.read_parquet((eod or files)[-1])


def div_yield(ticker, spot):
    """Trailing-12m dividends / spot. Best-effort; 0 with flag on failure."""
    try:
        import yfinance as yf
        d = yf.Ticker(ticker).dividends
        if d is None or d.empty:
            return 0.0, False
        d.index = pd.to_datetime(d.index, utc=True)
        tr = d[d.index >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=365)].sum()
        return float(tr) / spot, False
    except Exception:
        return 0.0, True


def earnings_in_window(ticker, until):
    try:
        import yfinance as yf
        ed = yf.Ticker(ticker).get_earnings_dates(limit=8)
        if ed is None or ed.empty:
            return False
        dates = pd.to_datetime(ed.index, utc=True)
        now = pd.Timestamp.now(tz="UTC")
        return bool(((dates > now) & (dates <= until)).any())
    except Exception:
        return False


def pcp_metrics(ch, spot, sofr, q, T_target_days):
    """Put-call parity at the strike nearest spot, expiry nearest target."""
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    ch = ch.copy()
    ch["T_days"] = (pd.to_datetime(ch.expiry) - now).dt.days
    ch = ch[ch.T_days >= 7]
    if ch.empty:
        return None
    expiry = ch.iloc[(ch.T_days - T_target_days).abs().argsort()].expiry.iloc[0]
    e = ch[ch.expiry == expiry]
    strikes = e[e.right == "C"].merge(e[e.right == "P"], on="strike",
                                      suffixes=("_c", "_p"))
    strikes = strikes[(strikes.bid_c > 0) & (strikes.ask_c > 0) &
                      (strikes.bid_p > 0) & (strikes.ask_p > 0)]
    if strikes.empty:
        return None
    row = strikes.iloc[(strikes.strike - spot).abs().argsort()].iloc[0]
    K = row.strike
    T = max((pd.to_datetime(expiry) - now).days, 1) / 365.0
    DF = np.exp(-sofr * T)
    mid_c = (row.bid_c + row.ask_c) / 2
    mid_p = (row.bid_p + row.ask_p) / 2
    F_mid = K + (mid_c - mid_p) / DF
    F_pess = K + (row.ask_c - row.bid_p) / DF   # entry-pessimistic: buy C@ask, sell P@bid
    c_mid = np.log(F_mid / spot) / T
    c_pess = np.log(max(F_pess, 1e-9) / spot) / T
    borrow_mid = sofr - q - c_mid
    half_spread_bps = ((row.ask_c - row.bid_c) + (row.ask_p - row.bid_p)) / 2 / spot * 1e4
    return dict(expiry=pd.Timestamp(expiry), T_days=int(T * 365), K=K,
                F_mid=F_mid, carry_mid=c_mid, carry_pess=c_pess,
                borrow_mid=borrow_mid, half_spread_bps=half_spread_bps,
                oi_pair=float(min(row.open_interest_c or 0, row.open_interest_p or 0)))


def convex_metrics(ch, spot):
    """~75-delta call at the ~30d expiry: annualized theta drag per delta-notional."""
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    ch = ch.copy()
    ch["T_days"] = (pd.to_datetime(ch.expiry) - now).dt.days
    calls = ch[(ch.right == "C") & (ch.T_days >= 7) & ch.delta.notna() &
               ch.theta.notna() & (ch.delta > 0.4)]
    if calls.empty:
        return None
    expiry = calls.iloc[(calls.T_days - 30).abs().argsort()].expiry.iloc[0]
    e = calls[calls.expiry == expiry]
    row = e.iloc[(e.delta - 0.75).abs().argsort()].iloc[0]
    atm = ch[(ch.right == "C") & (ch.expiry == expiry)]
    atm_iv = atm.iloc[(atm.strike - spot).abs().argsort()].iloc[0].iv if len(atm) else np.nan
    drag = abs(row.theta) * 365 / (row.delta * spot)
    return dict(c_delta=row.delta, c_strike=row.strike, theta_drag=drag,
                atm_iv=atm_iv, c_oi=row.open_interest)


def deribit_chain_usd(df):
    """Normalize Deribit chain to USD prices."""
    d = df.copy()
    if (d.settlement == "coin").any():
        for c in ["bid", "ask", "mark"]:
            d[c] = d[c] * d.underlying_price
    d["iv"] = d.mark_iv / 100.0
    d["delta"] = np.nan
    d["theta"] = np.nan
    d["open_interest"] = d.open_interest
    return d


def main():
    date_arg = None
    if "--date" in sys.argv:
        date_arg = sys.argv[sys.argv.index("--date") + 1]
    day_dir = latest_day_dir(date_arg)
    print(f"snapshot dir: {day_dir}")

    uni = pd.read_parquet(f"{OUT}/universe_v2.parquet")
    uni = uni[uni.in_universe]
    panel = pd.read_parquet(f"{OUT}/market_panel_v2.parquet")
    sofr = pd.read_parquet(f"{ROOT}/data/raw/rates/sofr_daily.parquet").sofr.iloc[-1] / 100

    div_cache, rows = {}, []
    for r in uni.itertuples():
        base = uni_mod.base_name(r.symbol)
        tkr = US_CHAIN_MAP.get(base)
        is_crypto = base in DERIBIT_NAMES
        if tkr is None and not is_crypto:
            continue
        g = panel[(panel.venue == r.venue) & (panel.symbol == r.symbol)]
        fund = operative_forecast(
            g.set_index("time")["funding_rate_1h"].sort_index(), r.venue, 30) * HY

        if is_crypto:
            raw = load_chain(day_dir, f"deribit_{base}")
            if raw is None or raw.empty:
                continue
            ch = deribit_chain_usd(raw)
            spot = float(raw.underlying_price.median())
            q, div_flag, earn = 0.0, False, False
            perp_tc = {"hyperliquid": 0.00065, "lighter": 0.0003}.get(r.venue, 0.0012)
        else:
            raw = load_chain(day_dir, f"cboe_{tkr}")
            if raw is None or raw.empty:
                continue
            ch = raw
            spot = float(raw.spot.iloc[0])
            if tkr not in div_cache:
                div_cache[tkr] = div_yield(tkr, spot)
            q, div_flag = div_cache[tkr]
            perp_tc = 0.0012 if r.venue == "hl_xyz" else 0.0003

        for bucket, tdays in BUCKETS.items():
            p = pcp_metrics(ch, spot, sofr, q, tdays)
            if p is None:
                continue
            earn = (earnings_in_window(tkr, p["expiry"].tz_localize("UTC"))
                    if not is_crypto else False)
            cx = convex_metrics(ch, spot) if bucket == "~30d" else None
            tc_ann = perp_tc * 12  # entry-only, amortized over 1m hold
            edge_synth = fund - p["carry_pess"] - tc_ann
            edge_spot = fund - (sofr + IBKR_SPREAD - q) - tc_ann
            rows.append({
                "venue": r.venue, "symbol": r.symbol, "name": base, "chain": tkr or base,
                "bucket": bucket, "T_days": p["T_days"], "spot": spot,
                "funding_1m_ann": fund, "carry_mid": p["carry_mid"],
                "carry_pess": p["carry_pess"], "borrow_mid": p["borrow_mid"],
                "edge_synth": edge_synth, "edge_spot_alt": edge_spot,
                "half_spread_bps": p["half_spread_bps"], "oi_pair": p["oi_pair"],
                "div_yield": q, "div_flag": div_flag, "earnings_in_window": earn,
                "atm_iv": cx["atm_iv"] if cx else np.nan,
                "theta_drag_ann": cx["theta_drag"] if cx else np.nan,
                "edge_convex": (fund - cx["theta_drag"] - tc_ann) if cx else np.nan,
                "c75_delta": cx["c_delta"] if cx else np.nan,
            })
        print(f"{r.venue}:{r.symbol} -> {tkr or base} done")

    df = pd.DataFrame(rows)
    df.to_parquet(f"{OUT}/options_rv.parquet", index=False)
    pd.set_option("display.width", 250)

    t30 = df[df.bucket == "~30d"].sort_values("edge_synth", ascending=False)
    cols = ["name", "venue", "funding_1m_ann", "carry_pess", "borrow_mid",
            "edge_synth", "edge_spot_alt", "edge_convex", "atm_iv",
            "half_spread_bps", "oi_pair", "earnings_in_window"]
    for min_oi in [0, 100, 1000]:
        sub = t30[t30.oi_pair >= min_oi]
        print(f"\n===== ~30d bucket, OI >= {min_oi} ({len(sub)} rows) =====")
        print(sub[cols].to_string(index=False, float_format=lambda x: f"{x:,.3f}"))


if __name__ == "__main__":
    main()
