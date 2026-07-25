"""Backtest v1: taker-entry, hold-to-present funding harvest.

Spec (Derek, 2026-07-24 — plan groovy-exploring-dragonfly):
  - Constructions: (1) short perp + long UNLEVERED cash equity/spot (no financing);
                   (2) short perp + long MARGINED equity (Reg-T 50/25, SOFR+spread financing).
  - Taker entry both legs; hold to present. Entry-date grid (daily).
  - Margin is an OUTPUT: minimal top-up path T(t) that keeps each leg >= maintenance,
    computed exactly via running-max of shortfall (top-up-to-maintenance-floor).

Per (pair, construction, leverage, entry_date) outputs a row in
data/processed/backtest_v1_results.parquet; per-pair example top-up series saved to
data/processed/backtest_v1_topups.parquet (heaviest entry date per pair x L).

Assumptions (explicit):
  - Perp mark ~ hourly candle close (venue trade price). HL liquidations actually use
    oracle-blended mark; candle close is the observable proxy.
  - Funding accrual = rate_1h(t) * mark(t) * qty, credited hourly to perp margin.
  - Short perp: pnl = qty*(P0 - P(t)) + funding_cum.
  - Equity valued at last session close between sessions; margin calls on the equity
    leg evaluated only at session hours. Perp legs evaluated 24/7.
  - Dividends credited on ex-date (daily table), no withholding modeled.
  - Fees (one-time entry, taker): see FEES/HALF_SPREAD below. No exit modeled
    (hold-to-present); exit cost would be ~ the same again.
  - Financing (construction 2): loan = 50% of initial stock value, accrues daily at
    (SOFR + IBKR_SPREAD); maintenance 25% of stock value.
  - KRW legs converted through hourly USDKRW (KRW=X), forward-filled.
"""
import os
import sys

import numpy as np
import pandas as pd

RAW = "/Users/dereklou/Projects/equity-perp/data/raw"
OUT = "/Users/dereklou/Projects/equity-perp/data/processed"

FEES = {"hyperliquid": 0.00045, "hl_xyz": 0.0009, "lighter": 0.0}  # taker, per side
HALF_SPREAD = {"hyperliquid": 0.0002, "hl_xyz": 0.0003, "lighter": 0.0003}
EQ_COST = 0.00015          # equity entry: half-spread + commission
SPOT_FEE = 0.0026          # crypto spot taker (Kraken-tier)
IBKR_SPREAD = 0.015        # financing = SOFR + this
REGT_INITIAL, REGT_MAINT = 0.5, 0.25
LEVERAGES = [1, 2, 3, 5]
MIN_HOLD_DAYS = 7

# pair spec: (pair_id, perp_venue, perp_symbol, hedge_kind, hedge_key, fx_key)
PAIRS = [
    ("SKHX/xyz-KRX",    "hl_xyz",      "xyz:SKHX",   "equity", "000660.KS", "KRW=X"),
    ("SKHYNIX/ltr-KRX", "lighter",     "SKHYNIXUSD", "equity", "000660.KS", "KRW=X"),
    ("MU/xyz",          "hl_xyz",      "xyz:MU",     "equity", "MU",   None),
    ("MU/ltr",          "lighter",     "MU",         "equity", "MU",   None),
    ("SNDK/xyz",        "hl_xyz",      "xyz:SNDK",   "equity", "SNDK", None),
    ("SNDK/ltr",        "lighter",     "SNDK",       "equity", "SNDK", None),
    ("SMSN/xyz",        "hl_xyz",      "xyz:SMSN",   "equity", "SMSN.IL", None),
    ("CRCL/xyz",        "hl_xyz",      "xyz:CRCL",   "equity", "CRCL", None),
    ("CRCL/ltr",        "lighter",     "CRCL",       "equity", "CRCL", None),
    ("NBIS/xyz",        "hl_xyz",      "xyz:NBIS",   "equity", "NBIS", None),
    ("HOOD/xyz",        "hl_xyz",      "xyz:HOOD",   "equity", "HOOD", None),
    ("ORCL/xyz",        "hl_xyz",      "xyz:ORCL",   "equity", "ORCL", None),
    ("INTC/xyz",        "hl_xyz",      "xyz:INTC",   "equity", "INTC", None),
    ("MRVL/xyz",        "hl_xyz",      "xyz:MRVL",   "equity", "MRVL", None),
    ("IBM/xyz",         "hl_xyz",      "xyz:IBM",    "equity", "IBM",  None),
    ("XMR/hl",          "hyperliquid", "XMR",        "spot",   "XMR",  None),
    ("ETH/hl",          "hyperliquid", "ETH",        "spot",   "ETH-USD", None),
    ("ETH/ltr",         "lighter",     "ETH",        "spot",   "ETH-USD", None),
    ("SOL/hl",          "hyperliquid", "SOL",        "spot",   "SOL-USD", None),
    ("BTC/hl",          "hyperliquid", "BTC",        "spot",   "BTC-USD", None),
]


# --------------------------------------------------------------- data loading
def load_all():
    hl = pd.read_parquet(f"{RAW}/hyperliquid/candles_1h_bt.parquet")
    ltr = pd.read_parquet(f"{RAW}/lighter/candles_1h.parquet")
    perp_px = {}
    for coin, g in hl.groupby("coin"):
        venue = "hl_xyz" if coin.startswith("xyz:") else "hyperliquid"
        perp_px[(venue, coin)] = g.set_index("time")["close"].sort_index()
    for sym, g in ltr.groupby("symbol"):
        perp_px[("lighter", sym)] = pd.to_numeric(
            g.set_index("time")["close"]).sort_index()

    fund = pd.read_parquet(f"{OUT}/expansion_funding_panel.parquet")
    fund["time"] = fund["time"].dt.floor("h")   # HL stamps carry ms offsets
    fmap = {}
    for (v, s), g in fund.groupby(["venue", "symbol"]):
        fmap[(v, s)] = g.groupby("time")["rate_1h"].sum().sort_index()

    eq_h = pd.read_parquet(f"{RAW}/equities/equity_1h.parquet")
    eq_d = pd.read_parquet(f"{RAW}/equities/equity_daily.parquet")
    eq_px, eq_div = {}, {}
    for tkr, g in eq_h.groupby("ticker"):
        # US bars sit on :30 (13:30 UTC open) — floor to the hourly grid
        s = g.assign(time=g["time"].dt.floor("h")).groupby("time")["close"].last()
        eq_px[tkr] = s.sort_index()
    for tkr, g in eq_d.groupby("ticker"):
        if "dividends" in g:
            d = g.set_index("time")["dividends"]
            eq_div[tkr] = d[d > 0]

    cb = pd.read_parquet(f"{RAW}/spot/coinbase_1h.parquet")
    for prod, g in cb.groupby("product"):
        eq_px[prod] = g.set_index("time")["close"].sort_index()
    kx = pd.read_parquet(f"{RAW}/spot/kucoin_xmr_1h.parquet")
    eq_px["XMR"] = kx.set_index("time")["close"].sort_index()

    sofr = pd.read_parquet(f"{RAW}/rates/sofr_daily.parquet")
    sofr_s = sofr.set_index(pd.to_datetime(sofr.date, utc=True))["sofr"] / 100.0

    snap = pd.read_parquet(f"{RAW}/hyperliquid/asset_ctx_snapshot_latest.parquet")
    mmf = {}
    for _, r in snap.iterrows():
        venue = "hyperliquid" if r.dex == "" else f"hl_{r.dex}"
        if r.maxLeverage:
            mmf[(venue, r["name"])] = 1.0 / (2 * r.maxLeverage)
    lmp = pd.read_parquet(f"{RAW}/lighter/margin_params.parquet")
    for _, r in lmp.iterrows():
        if pd.notna(r.maintenance_margin_fraction):
            mmf[("lighter", r.symbol)] = r.maintenance_margin_fraction / 1e4
    return perp_px, fmap, eq_px, eq_div, sofr_s, mmf


def running_topups(shortfall: np.ndarray) -> np.ndarray:
    """Minimal cumulative top-up path: T(t) = max(0, cummax(shortfall))."""
    return np.maximum(np.maximum.accumulate(shortfall), 0.0)


def main():
    perp_px, fmap, eq_px, eq_div, sofr_s, mmf = load_all()
    N = 100_000.0  # notional per pair (results scale linearly)
    results, topup_rows = [], []

    for pair_id, venue, psym, hkind, hkey, fxkey in PAIRS:
        if (venue, psym) not in perp_px or (venue, psym) not in fmap:
            print(f"skip {pair_id}: missing perp data")
            continue
        if hkey not in eq_px:
            print(f"skip {pair_id}: missing hedge data {hkey}")
            continue
        P = perp_px[(venue, psym)]
        F = fmap[(venue, psym)]
        H_raw = eq_px[hkey]
        if fxkey:
            fx = eq_px[fxkey]
            H_raw = (H_raw / fx.reindex(H_raw.index, method="ffill")).dropna()

        # hourly master grid = intersection of perp price & funding span
        t0 = max(P.index.min(), F.index.min(), H_raw.index.min())
        t1 = min(P.index.max(), F.index.max())
        grid = pd.date_range(t0.ceil("h"), t1.floor("h"), freq="h", tz="UTC")
        if len(grid) < 24 * (MIN_HOLD_DAYS + 1):
            print(f"skip {pair_id}: window too short")
            continue
        p = P.reindex(grid, method="ffill").to_numpy()
        f = F.reindex(grid).fillna(0.0).to_numpy()
        h = H_raw.reindex(grid, method="ffill").to_numpy()
        sess = grid.isin(H_raw.index)          # hedge tradeable this hour?
        valid = ~(np.isnan(p) | np.isnan(h))
        m = mmf.get((venue, psym), 0.05)

        div = np.zeros(len(grid))
        if hkind == "equity" and hkey in eq_div:
            dv = eq_div[hkey]
            for dt, amt in dv.items():
                ix = grid.searchsorted(dt)
                if 0 <= ix < len(grid):
                    if fxkey:   # dividend is in local currency -> USD at ex-date
                        fx_at = eq_px[fxkey][eq_px[fxkey].index <= dt]
                        if not len(fx_at):
                            continue
                        amt = amt / float(fx_at.iloc[-1])
                    div[ix] += amt
        sofr = sofr_s.reindex(grid, method="ffill").fillna(0.043).to_numpy()

        entry_ix = [i for i in range(len(grid) - 24 * MIN_HOLD_DAYS)
                    if valid[i] and sess[i]]
        # one entry per day: first eligible hour of each date
        seen, entries = set(), []
        for i in entry_ix:
            d = grid[i].date()
            if d not in seen:
                seen.add(d)
                entries.append(i)

        perp_cost = (FEES[venue] + HALF_SPREAD[venue]) * N
        hedge_cost = (EQ_COST if hkind == "equity" else SPOT_FEE) * N

        for i in entries:
            q = N / p[i]
            qh = N / h[i]
            yrs = (len(grid) - 1 - i) / (24 * 365)
            fund_cum = np.cumsum(f[i:] * p[i:] * q)
            perp_pnl = q * (p[i] - p[i:]) + fund_cum          # short perp
            div_cum = np.cumsum(div[i:]) * qh
            for L in LEVERAGES:
                if 1.0 / L <= m:      # leverage beyond venue max
                    continue
                M0 = N / L
                shortfall = m * q * p[i:] - (M0 + perp_pnl)
                T = running_topups(shortfall)
                # construction 1: cash equity/spot, no hedge leverage
                hedge_pnl = qh * (h[i:] - h[i]) + div_cum
                net1 = perp_pnl[-1] + hedge_pnl[-1] - perp_cost - hedge_cost
                cap1 = M0 + N + T[-1]
                # construction 2 (equity only): Reg-T margined stock
                if hkind == "equity":
                    loan0 = (1 - REGT_INITIAL) * N
                    fin = np.cumsum(np.where(np.diff(grid[i:].date,
                                                     prepend=grid[i].date()) != pd.Timedelta(0),
                                             loan0 * (sofr[i:] + IBKR_SPREAD) / 360, 0.0))
                    heq = qh * h[i:] - loan0 - fin + div_cum
                    hshort = np.where(sess[i:], REGT_MAINT * qh * h[i:] - heq, -np.inf)
                    Th = running_topups(hshort)
                    net2 = perp_pnl[-1] + (heq[-1] - REGT_INITIAL * N) - perp_cost - hedge_cost
                    cap2 = M0 + REGT_INITIAL * N + T[-1] + Th[-1]
                else:
                    net2, cap2, Th = np.nan, np.nan, None

                row = dict(pair=pair_id, venue=venue, entry=grid[i], L=L,
                           hold_days=round(yrs * 365, 1),
                           gross_funding=fund_cum[-1],
                           topup_perp=T[-1],
                           n_topups=int((np.diff(T, prepend=0) > 1e-9).sum()),
                           first_topup_day=(round(float(np.argmax(T > 1e-9)) / 24, 1)
                                            if T[-1] > 1e-9 else np.nan),
                           net_c1=net1, cap_c1=cap1,
                           ann_ret_c1=net1 / cap1 / yrs,
                           net_c2=net2, cap_c2=cap2,
                           ann_ret_c2=(net2 / cap2 / yrs) if cap2 == cap2 else np.nan,
                           topup_hedge=(Th[-1] if Th is not None else np.nan))
                results.append(row)
                if L == 2 and i == entries[len(entries) // 2]:
                    topup_rows.append(pd.DataFrame({
                        "pair": pair_id, "L": L, "entry": grid[i],
                        "time": grid[i:], "topup_cum_perp": T,
                        "perp_equity": M0 + perp_pnl + T}))
        print(f"{pair_id}: {len(entries)} entries simulated")

    res = pd.DataFrame(results)
    res.to_parquet(f"{OUT}/backtest_v1_results.parquet", index=False)
    if topup_rows:
        pd.concat(topup_rows, ignore_index=True).to_parquet(
            f"{OUT}/backtest_v1_topups.parquet", index=False)
    print(f"\nresults: {len(res)} rows -> backtest_v1_results.parquet")

    # summary: per pair x L, distribution over entry dates
    summ = (res.groupby(["pair", "L"])
            .agg(entries=("entry", "count"),
                 med_ann_c1=("ann_ret_c1", "median"),
                 p10_ann_c1=("ann_ret_c1", lambda x: x.quantile(.1)),
                 p90_ann_c1=("ann_ret_c1", lambda x: x.quantile(.9)),
                 med_ann_c2=("ann_ret_c2", "median"),
                 med_topup=("topup_perp", "median"),
                 max_topup=("topup_perp", "max"),
                 pct_entries_topped=("topup_perp", lambda x: (x > 1e-9).mean()))
            .reset_index())
    summ.to_parquet(f"{OUT}/backtest_v1_summary.parquet", index=False)
    pd.set_option("display.width", 250)
    print(summ.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))


if __name__ == "__main__":
    main()
