"""Step 3 — funding-rate forecast evaluation (LOCKED — see METHODOLOGY.md).

Spec (Derek, 2026-07-24): test configurations of three model classes for
forecasting the average funding rate over the next 7 days and 30 days,
evaluated on squared error:

  1. SMA(W)                 trailing mean over W days, extrapolated flat.
  2. EWMA(h)                exp-weighted mean, halflife h days, extrapolated flat.
  3. DECAY(hs, kappa, A)    level starts at EWMA(hs), decays exponentially with
                            timescale kappa days toward anchor A (zero | long
                            EWMA); forecast = horizon average of that path:
                            pred(H) = A + (E_hs - A) * (kappa/H)*(1 - exp(-H/kappa))

Locked evaluation protocol:
  - Data: market_panel_v2.parquet, in-universe markets only (universe v2).
    dYdX is out of universe and therefore out of this study by construction.
  - Targets: realized mean hourly funding over (t, t+7d] and (t, t+30d],
    annualized (x 8760). Origins: daily 00:00 UTC.
  - Requirements per origin: >=60d of funding history since the market's first
    observation; >=90% hour coverage on feature and target windows. Markets too
    short for a horizon drop out automatically (most Lighter markets: 1w only).
  - Error: RMSE in annualized units; cross-market aggregation via nRMSE
    (per-market RMSE / per-market target std), median across markets.
  - Baselines: ZERO (predict 0) and persistence (SMA with W = horizon, in-grid).
  - Champion selection is an OUTPUT (rerun on refresh), not part of the lock.

Grids: SMA W in {3,7,14,30,60}; EWMA h in {1,3,7,14,30,60};
       DECAY hs in {1,3,7} x kappa in {3,7,14,30,60} x A in {zero, ewma30, ewma60}.

Output: data/processed/funding_forecast_eval.parquet (+ printed leaderboards).
"""
import itertools

import numpy as np
import pandas as pd

OUT = "/Users/dereklou/Projects/equity-perp/data/processed"
HOURS_YR = 24 * 365
MIN_HIST_D = 60
COVERAGE = 0.90

SMA_W = [3, 7, 14, 30, 60]
EWMA_H = [1, 3, 7, 14, 30, 60]
DECAY_HS = [1, 3, 7]
DECAY_K = [3, 7, 14, 30, 60]
DECAY_ANCHOR = ["zero", "ewma30", "ewma60"]
HORIZONS = {"1w": 7, "1m": 30}


def evaluate_market(r: pd.Series, venue: str, sym: str) -> list[dict]:
    """r: hourly funding series (NaN gaps) on a regular hourly grid."""
    first = r.first_valid_index()
    if first is None:
        return []
    r = r.loc[first:]
    grid = r.index

    sma = {W: r.rolling(W * 24, min_periods=int(W * 24 * COVERAGE)).mean()
           for W in SMA_W}
    ewma = {h: r.ewm(halflife=h * 24, min_periods=int(min(h, 10) * 24),
                     ignore_na=True).mean()
            for h in sorted(set(EWMA_H + DECAY_HS + [30, 60]))}
    fwd = {}
    for tag, H in HORIZONS.items():
        n = H * 24
        f = r.iloc[::-1].rolling(n, min_periods=int(n * COVERAGE)).mean().iloc[::-1]
        fwd[tag] = f.shift(-1)

    day0 = grid[grid.searchsorted(first + pd.Timedelta(days=MIN_HIST_D))] \
        if first + pd.Timedelta(days=MIN_HIST_D) <= grid[-1] else None
    if day0 is None:
        return []
    origins = pd.date_range(day0.ceil("D"), grid[-1].floor("D"), freq="D", tz="UTC")
    oix = grid.searchsorted(origins)
    oix = oix[oix < len(grid)]

    rows = []
    for tag, H in HORIZONS.items():
        y = fwd[tag].to_numpy()[oix] * HOURS_YR
        ok = ~np.isnan(y)
        if ok.sum() < 10:
            continue
        preds = {}
        for W in SMA_W:
            preds[("SMA", f"W={W}")] = sma[W].to_numpy()[oix] * HOURS_YR
        for h in EWMA_H:
            preds[("EWMA", f"h={h}")] = ewma[h].to_numpy()[oix] * HOURS_YR
        for hs, k, anc in itertools.product(DECAY_HS, DECAY_K, DECAY_ANCHOR):
            E = ewma[hs].to_numpy()[oix] * HOURS_YR
            A = (np.zeros_like(E) if anc == "zero"
                 else ewma[int(anc[4:])].to_numpy()[oix] * HOURS_YR)
            w = (k / H) * (1 - np.exp(-H / k))
            preds[("DECAY", f"hs={hs},k={k},A={anc}")] = A + (E - A) * w
        preds[("BASE", "zero")] = np.zeros(len(oix))

        y_std = np.nanstd(y[ok])
        for (mclass, param), p in preds.items():
            m = ok & ~np.isnan(p)
            if m.sum() < 10:
                continue
            mse = float(np.mean((p[m] - y[m]) ** 2))
            rows.append({"venue": venue, "symbol": sym, "horizon": tag,
                         "model": mclass, "param": param, "n": int(m.sum()),
                         "rmse": np.sqrt(mse),
                         "nrmse": np.sqrt(mse) / y_std if y_std > 0 else np.nan,
                         "target_std": y_std,
                         "target_mean": float(np.nanmean(y[ok]))})
    return rows


# -------------------------------------------------------------- operative model
def operative_forecast(r: pd.Series, venue: str, horizon_days: int) -> float:
    """LOCKED operative expected-funding forecast (see METHODOLOGY.md decision log).

    r: hourly funding series (decimal/hour, NaN gaps). Returns expected mean
    hourly funding over the next horizon_days, evaluated at the series end.

    ALL venues: flat EWMA — halflife 30d for the 1-week horizon, 60d for the
    1-month horizon. On young markets (history < halflife) the adjusted EWMA
    gracefully approximates the expanding mean — intended behavior.

    Revision 2026-07-25 (Derek): the Lighter-specific zero-anchor decay model
    (0.23 x EWMA3 at 1m) was RETIRED — diagnostics + a relaxed-gate 1m
    head-to-head showed structural under-forecast of Lighter equity carry
    (median bias -7pp; SKHYNIX -76pp); its original support was a 1-week-only
    eval on ~22 tail origins, never a 1-month result. Caveat: Lighter commodity
    perps (WTI/BRENTOIL) showed genuine funding collapse where decay was better
    — re-examine after the Lighter history extension.
    """
    h = 30 if horizon_days <= 7 else 60
    return r.ewm(halflife=h * 24, min_periods=int(min(h, 10) * 24),
                 ignore_na=True).mean().iloc[-1]


def main():
    panel = pd.read_parquet(f"{OUT}/market_panel_v2.parquet")
    rows = []
    for (venue, sym), g in panel.groupby(["venue", "symbol"]):
        r = g.set_index("time")["funding_rate_1h"].sort_index()
        rows.extend(evaluate_market(r, venue, sym))
    ev = pd.DataFrame(rows)
    ev.to_parquet(f"{OUT}/funding_forecast_eval.parquet", index=False)

    pd.set_option("display.width", 220)
    print(f"evaluated: {ev.groupby('horizon')['symbol'].nunique().to_dict()} markets "
          f"per horizon, {len(ev)} result rows")
    for tag in HORIZONS:
        sub = ev[ev.horizon == tag]
        agg = (sub.groupby(["model", "param"])
               .agg(mkts=("symbol", "nunique"), med_nrmse=("nrmse", "median"),
                    mean_nrmse=("nrmse", "mean"), med_rmse=("rmse", "median"))
               .reset_index().sort_values("med_nrmse"))
        print(f"\n===== {tag}: top 12 by median nRMSE (lower better) =====")
        print(agg.head(12).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
        base = agg[(agg.model == "BASE") |
                   (agg.param == f"W={7 if tag == '1w' else 30}")]
        print(base.to_string(index=False, float_format=lambda x: f"{x:.3f}"))


if __name__ == "__main__":
    main()
