"""Cross-venue funding panel + harvest metrics (expansion study, 2026-07-24).

Normalizes every venue's funding history to one schema:
    (venue, symbol, time_utc_hour, rate_1h_decimal)   positive = longs pay shorts
then computes per (venue, symbol):
    magnitude  : annualized mean funding over 30d / 90d
    stability  : ann. std of daily funding, funding sharpe, % days positive,
                 worst rolling 7d sum (annualized)
    legitimacy : 24h notional volume, OI usd, vol/OI, category bucket
and a cross-venue matrix for symbols listed on >=2 venues.

Outputs:
  data/processed/expansion_funding_panel.parquet   (hourly normalized panel)
  data/processed/expansion_stats.parquet           (per venue x symbol metrics)
  data/processed/expansion_cross_venue.parquet     (per symbol venue spreads)

Unit conventions verified:
  HL / Extended / dYdX: hourly decimal rate per funding record (hourly interval).
  Aster: decimal per interval; interval inferred per symbol from median gap.
  Lighter: 'rate' is PERCENT per hour (verified vs HL same-coin overlap; /100 here),
           direction 'long' => longs pay (positive).
"""
import numpy as np
import pandas as pd

RAW = "/Users/dereklou/Projects/equity-perp/data/raw"
OUT = "/Users/dereklou/Projects/equity-perp/data/processed"

HOURS_YEAR = 24 * 365

# ------------------------------------------------------------------ categories
MEMES = {
    "DOGE", "SHIB", "PEPE", "1000PEPE", "kPEPE", "WIF", "BONK", "kBONK", "1000BONK",
    "FARTCOIN", "PUMP", "TRUMP", "MELANIA", "MOODENG", "POPCAT", "MEW", "BRETT",
    "GOAT", "PNUT", "CHILLGUY", "AI16Z", "SPX", "SPX6900", "MOG", "TURBO", "NEIRO",
    "1000FLOKI", "kFLOKI", "FLOKI", "BOME", "WEN", "SLERF", "MYRO", "BABYDOGE",
    "1MBABYDOGE", "DOGS", "HIPPO", "PENGU", "FWOG", "GIGA", "PONKE", "USELESS",
    "TROLL", "BASED", "YZY", "4", "APEPE", "CASHCAT", "MOND",
    "VINE", "PURR", "GRIFFAIN",
}
STOCKS = {
    "MU", "SNDK", "SKHYNIX", "SKHX", "SKHY", "CRCL", "HOOD", "TSLA", "NVDA",
    "AAPL", "MSFT", "META", "AMZN", "GOOG", "GOOGL", "ORCL", "INTC", "AMD",
    "COIN", "PLTR", "MSTR", "NFLX", "TSM", "OPENAI", "SPACEX", "SPCX", "AVGO",
    "APP", "UNH", "LLY", "BABA", "GME", "KIOXIA", "IBIDEN", "SOFTBANK",
    "TENCENT", "XIAOMI", "SMSN", "HYUNDAI", "CRWV", "SMCI", "RDDT", "UBER",
    "SNOW", "SHOP", "SQ", "ABNB", "IWM", "QQQ", "SPY", "DIA", "SP500",
    "XYZ100", "NDX", "US500", "USTECH",
}
MAJORS = {"BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "AVAX", "LINK", "LTC", "BCH",
          "DOT", "TON", "TRX", "XLM", "NEAR", "XMR", "ZEC", "ETC", "SUI", "HYPE"}
_COMMODITY_METAL = {"GOLD", "SILVER", "PLATINUM", "PALLADIUM", "COPPER", "XAU", "XAG",
                    "BRENTOIL", "CL", "OIL", "USOIL", "WTI", "NATGAS", "GAS", "TTF",
                    "CORN", "WHEAT", "SOY", "URANIUM", "COCOA", "COFFEE", "SUGAR"}
_FX = {"EUR", "GBP", "JPY", "KRW", "DXY", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD",
       "USDCAD", "USDCHF", "USDMXN", "NZDUSD"}


def base_of(symbol: str) -> str:
    s = symbol.upper()
    for suf in ["-USD", "-PERP", "USDT", "USDC", "USD", "PERP"]:
        if s.endswith(suf):
            s = s[: -len(suf)]
            break
    return s.strip("-_")


def categorize(venue: str, symbol: str, asset_class_hint: str | None = None) -> str:
    if asset_class_hint in {"single_stock", "equity_index"}:
        return "rwa_equity"
    if asset_class_hint in {"precious_metal", "commodity"}:
        return "commodity_metal"
    if asset_class_hint == "fx":
        return "fx"
    b = base_of(symbol.split(":")[-1])
    if b in STOCKS or b.removesuffix("_24_5") in STOCKS:
        return "rwa_equity"
    if b in MEMES or b.lstrip("K1M0") in MEMES:
        return "memecoin"
    if b in _COMMODITY_METAL:
        return "commodity_metal"
    if b in _FX:
        return "fx"
    if b in MAJORS:
        return "major_crypto"
    return "alt_crypto"


# ------------------------------------------------------------------ loaders
def load_hl():
    frames = []
    main = pd.read_parquet(f"{RAW}/hyperliquid/funding_history_maindex.parquet")
    main["venue"] = "hyperliquid"
    main["symbol"] = main.coin
    frames.append(main[["venue", "symbol", "time", "fundingRate"]])

    b = pd.read_parquet(f"{RAW}/hyperliquid/funding_history.parquet")
    b["venue"] = "hl_" + b.dex
    b["symbol"] = b.coin
    frames.append(b[["venue", "symbol", "time", "fundingRate"]])
    df = pd.concat(frames, ignore_index=True).rename(columns={"fundingRate": "rate_1h"})
    return df


def load_dydx():
    df = pd.read_parquet(f"{RAW}/dydx/dydx_funding_history.parquet")
    return pd.DataFrame({"venue": "dydx", "symbol": df.ticker,
                         "time": df.effectiveAt, "rate_1h": df.rate})


def load_lighter():
    df = pd.read_parquet(f"{RAW}/lighter/lighter_funding_history.parquet")
    return pd.DataFrame({"venue": "lighter", "symbol": df.symbol,
                         "time": df.time, "rate_1h": df.rate_signed / 100.0})


def load_aster():
    frames = []
    for f, tag in [("aster_crypto_funding_history.parquet", "crypto"),
                   ("aster_funding_history.parquet", "rwa")]:
        try:
            d = pd.read_parquet(f"{RAW}/longtail/{f}")
        except FileNotFoundError:
            continue
        d = d[["symbol", "fundingTime", "fundingRate"]].copy()
        frames.append(d)
    df = pd.concat(frames, ignore_index=True).drop_duplicates(["symbol", "fundingTime"])
    # infer per-symbol funding interval (hours) from median gap
    df = df.sort_values(["symbol", "fundingTime"])
    gap = (df.groupby("symbol")["fundingTime"].diff().dt.total_seconds() / 3600)
    iv = gap.groupby(df.symbol).median().clip(lower=1).round()
    df["interval_h"] = df.symbol.map(iv).fillna(8)
    return pd.DataFrame({"venue": "aster", "symbol": df.symbol, "time": df.fundingTime,
                         "rate_1h": df.fundingRate / df.interval_h})


def load_extended():
    df = pd.read_parquet(f"{RAW}/longtail/extended_funding_all.parquet")
    return pd.DataFrame({"venue": "extended", "symbol": df.market,
                         "time": df.time, "rate_1h": df.fundingRate})


# ------------------------------------------------------------------ metrics
def compute_stats(panel: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    rows = []
    for (venue, sym), g in panel.groupby(["venue", "symbol"]):
        g = g.sort_values("time")
        daily = g.set_index("time").rate_1h.resample("1D").sum()
        # require some minimum history
        d30 = daily[daily.index >= asof - pd.Timedelta(days=30)]
        d90 = daily[daily.index >= asof - pd.Timedelta(days=90)]
        if len(d30.dropna()) < 10:
            continue
        ann30 = d30.mean() * 365
        ann90 = d90.mean() * 365 if len(d90) >= 30 else np.nan
        std_ann = d30.std() * np.sqrt(365)
        roll7 = d90.rolling(7).sum()
        rows.append({
            "venue": venue, "symbol": sym,
            "n_days": len(d90),
            "ann_funding_30d": ann30,
            "ann_funding_90d": ann90,
            "ann_std_daily_30d": std_ann,
            "funding_sharpe_30d": ann30 / std_ann if std_ann and std_ann > 0 else np.nan,
            "pct_days_pos_90d": (d90 > 0).mean(),
            "worst_7d_ann_90d": roll7.min() * 52 if roll7.notna().any() else np.nan,
            "best_7d_ann_90d": roll7.max() * 52 if roll7.notna().any() else np.nan,
            "last_time": g.time.max(),
        })
    return pd.DataFrame(rows)


def attach_liquidity(stats: pd.DataFrame) -> pd.DataFrame:
    liq = {}  # (venue, symbol) -> dict

    snap = pd.read_parquet(f"{RAW}/hyperliquid/asset_ctx_snapshot_latest.parquet")
    for _, r in snap.iterrows():
        venue = "hyperliquid" if r.dex == "" else f"hl_{r.dex}"
        liq[(venue, r["name"])] = {
            "vol24h_usd": r.dayNtlVlm,
            "oi_usd": (r.openInterest or 0) * (r.markPx or 0),
            "asset_class_hint": r.asset_class,
        }

    dm = pd.read_parquet(f"{RAW}/dydx/dydx_markets.parquet")
    for _, r in dm.iterrows():
        liq[("dydx", r.ticker)] = {"vol24h_usd": r.volume24H,
                                   "oi_usd": r.openInterest_usd, "asset_class_hint": None}

    lm = pd.read_parquet(f"{RAW}/lighter/lighter_markets.parquet")
    for _, r in lm.iterrows():
        liq[("lighter", r.symbol)] = {"vol24h_usd": r.daily_quote_volume,
                                      "oi_usd": r.open_interest_usd, "asset_class_hint": None}

    at = pd.read_parquet(f"{RAW}/longtail/aster_all_ticker24h.parquet")
    for _, r in at.iterrows():
        liq[("aster", r.symbol)] = {
            "vol24h_usd": r.quoteVolume, "oi_usd": np.nan,
            "asset_class_hint": "single_stock" if r.is_rwa else None}

    em = pd.read_parquet(f"{RAW}/longtail/extended_markets_latest.parquet")
    for _, r in em.iterrows():
        hint = "single_stock" if r.category == "TradFi" else None
        liq[("extended", r["name"])] = {"vol24h_usd": r.dailyVolume,
                                        "oi_usd": r.openInterest, "asset_class_hint": hint}

    stats = stats.copy()
    stats["vol24h_usd"] = [liq.get((v, s), {}).get("vol24h_usd", np.nan)
                           for v, s in zip(stats.venue, stats.symbol)]
    stats["oi_usd"] = [liq.get((v, s), {}).get("oi_usd", np.nan)
                       for v, s in zip(stats.venue, stats.symbol)]
    stats["category"] = [categorize(v, s, liq.get((v, s), {}).get("asset_class_hint"))
                         for v, s in zip(stats.venue, stats.symbol)]
    stats["vol_oi_ratio"] = stats.vol24h_usd / stats.oi_usd
    return stats


def cross_venue(panel: pd.DataFrame, stats: pd.DataFrame) -> pd.DataFrame:
    p = panel.copy()
    p["base"] = [base_of(s.split(":")[-1]) for s in p.symbol]
    p["hour"] = p.time.dt.floor("h")
    cutoff = p.time.max() - pd.Timedelta(days=30)
    p = p[p.time >= cutoff]
    # per-venue independent 30d means (interval venues have sparse hourly grids,
    # so a common-window join would silently drop them); require >=15d coverage
    p["date"] = p.time.dt.floor("D")
    agg = (p.groupby(["base", "venue"])
             .agg(mean_1h=("rate_1h", "mean"), n_days=("date", "nunique"),
                  n_hours=("hour", "nunique")).reset_index())
    agg = agg[agg.n_days >= 15]
    rows = []
    for b, g in agg.groupby("base"):
        if g.venue.nunique() < 2:
            continue
        means = g.set_index("venue").mean_1h * HOURS_YEAR
        rows.append({
            "base": b, "n_venues": len(means), "n_hours": int(g.n_hours.min()),
            "max_venue": means.idxmax(), "min_venue": means.idxmin(),
            "ann_spread": means.max() - means.min(),
            **{f"ann_{v}": means.get(v, np.nan) for v in means.index},
        })
    return pd.DataFrame(rows).sort_values("ann_spread", ascending=False)


def main():
    asof = pd.Timestamp.now(tz="UTC").floor("h")
    parts = []
    for name, fn in [("hl", load_hl), ("dydx", load_dydx), ("lighter", load_lighter),
                     ("aster", load_aster), ("extended", load_extended)]:
        try:
            d = fn()
            d = d.dropna(subset=["time", "rate_1h"])
            print(f"{name}: {len(d)} rows, {d.symbol.nunique()} symbols")
            parts.append(d)
        except Exception as e:
            print(f"{name} FAILED: {e!r}")
    panel = pd.concat(parts, ignore_index=True)
    panel = panel[panel.time >= asof - pd.Timedelta(days=185)]
    panel.to_parquet(f"{OUT}/expansion_funding_panel.parquet", index=False)

    stats = compute_stats(panel, asof)
    stats = attach_liquidity(stats)
    stats.to_parquet(f"{OUT}/expansion_stats.parquet", index=False)
    print(f"stats: {len(stats)} venue-symbols")

    cv = cross_venue(panel, stats)
    cv.to_parquet(f"{OUT}/expansion_cross_venue.parquet", index=False)
    print(f"cross_venue: {len(cv)} bases")

    # quick sanity print: Lighter vs HL unit check on BTC/ETH
    for b in ["BTC", "ETH"]:
        chk = panel[panel.symbol.isin([b])].copy()
        chk["hour"] = chk.time.dt.floor("h")
        w = chk.pivot_table(index="hour", columns="venue", values="rate_1h")
        if {"hyperliquid", "lighter"} <= set(w.columns):
            w = w.dropna()
            print(f"unit check {b}: HL ann={w.hyperliquid.mean()*HOURS_YEAR:.3%} "
                  f"lighter ann={w.lighter.mean()*HOURS_YEAR:.3%} "
                  f"corr={w.hyperliquid.corr(w.lighter):.2f} n={len(w)}")


if __name__ == "__main__":
    main()
