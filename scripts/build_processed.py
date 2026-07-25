"""Build processed analysis tables from raw parquets.

Outputs (data/processed/):
  funding_stats.parquet      — per venue/asset funding-rate stats, all rates annualized
  funding_rolling7d.parquet  — 7d rolling annualized funding per venue/asset (deviation analysis)
  volume_by_class_24h.parquet— 24h notional volume & OI by venue x asset_class (snapshot 2026-07-11, weekend)
  basis_econ.parquet         — first-order basis-trade economics for top RWA assets

Run: .venv/bin/python scripts/build_processed.py
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data/raw", ROOT / "data/processed"
OUT.mkdir(parents=True, exist_ok=True)

HOURS_YR = 24 * 365

# ---------------------------------------------------------------- asset class
EQ_INDEX = {"SP500", "SPX", "XYZ100", "NDX", "US500", "US100", "JP225", "NIFTY", "KR200",
            "IBOV", "DJ30", "FTSE", "HSI", "DAX", "SPY", "QQQ", "IWM", "DIA", "EWJ", "EWT",
            "EWY", "EWZ", "SMH", "XLE", "URNM", "GDX", "URA", "VIX"}
METALS = {"GOLD", "XAU", "SILVER", "XAG", "PLATINUM", "XPT", "PALLADIUM", "XPD", "COPPER", "HG"}
COMMODS = {"CL", "WTI", "BRENTOIL", "NATGAS", "TTF", "CORN", "WHEAT", "URANIUM", "DRAM",
           "H100", "ALUMINIUM", "SKHX", "SKHY", "SNDK", "XNG", "XBR", "BZ", "NG", "XCU"}
FX = {"EUR", "GBP", "JPY", "KRW", "AUD", "NZD", "CAD", "CHF", "MXN", "DXY", "EURUSD", "USDJPY", "GBPUSD"}
CRYPTO_HINTS = {"BTC", "ETH", "SOL", "HYPE", "DOGE", "XRP", "ADA", "AVAX", "LINK", "BNB",
                "SUI", "LTC", "TON", "TRX", "PEPE", "WIF", "ENA", "PURR", "FARTCOIN", "KPEPE",
                "KBONK", "KSHIB", "ASTER", "ZEC", "PUMP", "WLFI", "LINEA", "XPL", "MON", "MEME"}

def classify(sym: str) -> str:
    s = sym.upper().replace("-USD", "").replace("USDT", "").replace("USD", "").replace("-PERP", "")
    s = s.split(":")[-1].rstrip("X") if s.endswith("X") and len(s) > 3 else s.split(":")[-1]
    s = s.split(":")[-1]
    if s in METALS: return "precious_metal" if s in {"GOLD","XAU","SILVER","XAG","PLATINUM","XPT","PALLADIUM","XPD"} else "commodity"
    if s in EQ_INDEX: return "equity_index"
    if s in COMMODS: return "commodity"
    if s in FX: return "fx"
    if s in CRYPTO_HINTS or len(s) <= 2: return "crypto"
    return "single_stock"  # default for remaining tickers; venue tables override where they carry a class

# ---------------------------------------------------------------- load funding, normalized to hourly panels
panels = []  # venue, coin, time (UTC), hourly_rate

hl = pd.read_parquet(RAW / "hyperliquid/funding_history.parquet")
hl["venue"] = "hyperliquid:" + hl["dex"]
hl = hl.rename(columns={"coin": "symbol", "fundingRate": "hourly_rate"})
panels.append(hl[["venue", "symbol", "time", "hourly_rate", "premium"]])

vest = pd.read_parquet(RAW / "longtail/vest_funding_history.parquet")
vest["venue"] = "vest"
vest = vest.rename(columns={"oneHrFundingRate": "hourly_rate"})
vest["premium"] = np.nan
panels.append(vest[["venue", "symbol", "time", "hourly_rate", "premium"]])

ast = pd.read_parquet(RAW / "longtail/aster_funding_history.parquet")
ast = ast.sort_values(["symbol", "fundingTime"])
iv = ast.groupby("symbol")["fundingTime"].diff().dt.total_seconds().div(3600)
ast["interval_h"] = iv.groupby(ast["symbol"]).transform("median").fillna(8).clip(1, 24)
ast["hourly_rate"] = ast["fundingRate"] / ast["interval_h"]
ast["venue"], ast["premium"] = "aster", np.nan
panels.append(ast.rename(columns={"fundingTime": "time"})[["venue", "symbol", "time", "hourly_rate", "premium"]])

ext = pd.read_parquet(RAW / "longtail/extended_funding_history.parquet")
ext["venue"] = "extended"
ext = ext.rename(columns={"market": "symbol", "fundingRate": "hourly_rate"})
ext["premium"] = np.nan
panels.append(ext[["venue", "symbol", "time", "hourly_rate", "premium"]])

hx = pd.read_parquet(RAW / "longtail/helix_funding_history.parquet")
hx["venue"] = "helix"
hx["symbol"] = hx["ticker"].str.replace("/USDC PERP", "", regex=False).str.replace(" PERP", "", regex=False)
hx = hx.rename(columns={"rate": "hourly_rate", "timestamp": "time"})
hx["premium"] = np.nan
panels.append(hx[["venue", "symbol", "time", "hourly_rate", "premium"]])

fund = pd.concat(panels, ignore_index=True)
fund["time"] = pd.to_datetime(fund["time"], utc=True)
fund["asset_class"] = fund["symbol"].map(classify)

# Ostium: daily fractions -> keep separate (different mechanics: one-sided rollover + funding)
ost = pd.read_parquet(RAW / "ostium/funding_history.parquet")
ost["date"] = pd.to_datetime(ost["date"], utc=True)
ostp = pd.read_parquet(RAW / "ostium/pairs_snapshot.parquet")[["pair_id", "asset_class", "from_sym", "to_sym"]]
ost = ost.merge(ostp[["pair_id", "asset_class"]], on="pair_id", how="left")
ost["symbol"] = ost["from_sym"] + "/" + ost["to_sym"]

# ---------------------------------------------------------------- funding stats (annualized)
def ann_stats(g: pd.DataFrame) -> pd.Series:
    r = g["hourly_rate"].dropna()
    days = (g["time"].max() - g["time"].min()).days
    roll7 = r.rolling(24 * 7).mean() * HOURS_YR  # 7d window annualized
    return pd.Series({
        "n_obs": len(r), "days_history": days,
        "first": g["time"].min(), "last": g["time"].max(),
        "ann_funding_mean": r.mean() * HOURS_YR,
        "ann_funding_last30d": g.loc[g["time"] > g["time"].max() - pd.Timedelta(days=30), "hourly_rate"].mean() * HOURS_YR,
        "ann_funding_vol_hourly": r.std() * HOURS_YR,      # std of hourly rate, annualized units
        "pct_hours_positive": (r > 0).mean(),
        "pct_hours_at_floor": (r.abs() < 1e-9).mean(),
        "ann_p5_7d": roll7.quantile(0.05), "ann_p95_7d": roll7.quantile(0.95),
        "ann_min_7d": roll7.min(), "ann_max_7d": roll7.max(),
        "mean_abs_premium_bps": g["premium"].abs().mean() * 1e4 if g["premium"].notna().any() else np.nan,
    })

fs = fund.sort_values("time").groupby(["venue", "symbol", "asset_class"]).apply(ann_stats, include_groups=False).reset_index()

# Ostium daily -> annualized (x365). Regime migrated 2025-10-19 to per-side rollover
# (dominant side pays, other side receives; legacy funding accumulators frozen for RWA
# since 2025-03). Effective per-side carry = funding + per-side rollover.
def ost_stats(g: pd.DataFrame) -> pd.Series:
    g = g.copy()
    g["eff_long"] = g["funding_long_frac"].fillna(0) + g["rollover_long_frac"].fillna(0)
    g["eff_short"] = g["funding_short_frac"].fillna(0) + g["rollover_short_frac"].fillna(0)
    g90 = g[g["date"] > g["date"].max() - pd.Timedelta(days=90)]
    g30 = g[g["date"] > g["date"].max() - pd.Timedelta(days=30)]
    return pd.Series({
        "n_obs": len(g), "days_history": (g["date"].max() - g["date"].min()).days,
        "first": g["date"].min(), "last": g["date"].max(),
        "ann_eff_long_90d": g90["eff_long"].mean() * 365,
        "ann_eff_short_90d": g90["eff_short"].mean() * 365,
        "ann_eff_long_30d": g30["eff_long"].mean() * 365,
        "ann_eff_short_30d": g30["eff_short"].mean() * 365,
        "eff_long_vol_ann_90d": g90["eff_long"].std() * 365,
        "ann_legacy_funding_long": g["funding_long_frac"].mean() * 365,
        "ann_legacy_rollover": g["rollover_frac"].mean() * 365,
    })

ofs = ost.sort_values("date").groupby(["symbol", "asset_class"]).apply(ost_stats, include_groups=False).reset_index()
ofs.insert(0, "venue", "ostium")

fs.to_parquet(OUT / "funding_stats.parquet", index=False)
ofs.to_parquet(OUT / "funding_stats_ostium.parquet", index=False)

# rolling 7d annualized funding panel (deviation/tradeability analysis)
fund_s = fund.sort_values(["venue", "symbol", "time"]).set_index("time")
roll = (fund_s.groupby(["venue", "symbol"])["hourly_rate"]
        .rolling("7D").mean().mul(HOURS_YR).rename("ann_funding_7d").reset_index())
roll["asset_class"] = roll["symbol"].map(classify)
roll.to_parquet(OUT / "funding_rolling7d.parquet", index=False)

# ---------------------------------------------------------------- 24h volume & OI by venue x class
rows = []
snap = pd.read_parquet(RAW / "hyperliquid/asset_ctx_snapshot.parquet")
snap = snap[snap["dex"] != ""]  # builder dexes only
for (dex, ac), g in snap.groupby(["dex", "asset_class"]):
    rows.append(("hyperliquid:" + dex, ac, g["dayNtlVlm"].sum(), (g["openInterest"] * g["markPx"]).sum(), len(g)))
ostp2 = pd.read_parquet(RAW / "ostium/pairs_snapshot.parquet")
vol_o = pd.read_parquet(RAW / "ostium/daily_volume.parquet")
last_day = vol_o[~vol_o["partial_day"]]["date"].max()
v24 = vol_o[vol_o["date"] == last_day].set_index("pair_id")["volume_usd"]
ostp2["v24"] = ostp2["pair_id"].map(v24)
for ac, g in ostp2.groupby("asset_class"):
    rows.append(("ostium", ac, g["v24"].sum(), (g["long_oi_usd"] + g["short_oi_usd"]).sum(), len(g)))
astt = pd.read_parquet(RAW / "longtail/aster_ticker24h.parquet").merge(
    pd.read_parquet(RAW / "longtail/aster_symbols.parquet")[["symbol", "is_rwa"]], on="symbol", how="left")
astt["asset_class"] = astt["symbol"].map(classify)
for ac, g in astt[astt["is_rwa"] == True].groupby("asset_class"):
    rows.append(("aster", ac, g["quoteVolume"].sum(), np.nan, len(g)))
vt = pd.read_parquet(RAW / "longtail/vest_ticker24h.parquet")
vt["asset_class"] = vt["symbol"].map(classify)
for ac, g in vt[vt["asset_class"] != "crypto"].groupby("asset_class"):
    rows.append(("vest", ac, g["quoteVolume"].sum(), np.nan, len(g)))
par = pd.read_parquet(RAW / "longtail/paradex_summary.parquet").merge(
    pd.read_parquet(RAW / "longtail/paradex_markets.parquet")[["symbol", "is_rwa"]], on="symbol", how="left")
par["asset_class"] = par["symbol"].map(classify)
for ac, g in par[par["is_rwa"] == True].groupby("asset_class"):
    rows.append(("paradex", ac, (g["volume_24h"]).sum(), (g["open_interest"] * g["mark_price"]).sum(), len(g)))
em = pd.read_parquet(RAW / "longtail/extended_markets.parquet")
em = em[(em["category"] == "TradFi") & em["active"]]
em["asset_class"] = em["assetName"].map(classify)
for ac, g in em.groupby("asset_class"):  # extended openInterest is already USD notional
    rows.append(("extended", ac, g["dailyVolume"].sum(), g["openInterest"].sum(), len(g)))
gp = pd.read_parquet(RAW / "longtail/gains_pairs_snapshot.parquet")
gp = gp[(gp["chain"] == "arbitrum") & (~gp["is_suspended"]) & (gp["asset_class"] != "crypto")]
for ac, g in gp.groupby("asset_class"):
    rows.append(("gains-arb", ac, np.nan, (g["oi_long_usd"] + g["oi_short_usd"]).sum(), len(g)))
av = pd.read_parquet(RAW / "longtail/avantis_pairs_snapshot.parquet")
av = av[av["is_listed"] & (av["asset_class"] != "crypto")]
if "oi_long_usd" in av.columns:
    for ac, g in av.groupby("asset_class"):
        rows.append(("avantis", ac, np.nan, (g["oi_long_usd"] + g["oi_short_usd"]).sum(), len(g)))
vbc = pd.DataFrame(rows, columns=["venue", "asset_class", "vol_24h_usd", "oi_usd", "n_assets"])
CLASS_MAP = {"stocks": "single_stock", "commodities": "commodity", "indices": "equity_index",
             "forex": "fx", "etf": "equity_index", "metals": "precious_metal"}
vbc["asset_class"] = vbc["asset_class"].replace(CLASS_MAP)
vbc = vbc.groupby(["venue", "asset_class"], as_index=False).sum()
vbc.to_parquet(OUT / "volume_by_class_24h.parquet", index=False)

# ---------------------------------------------------------------- monthly RWA volume trajectory per venue
traj = []
hlc = pd.read_parquet(RAW / "hyperliquid/daily_candles.parquet")
hlc["month"] = pd.to_datetime(hlc["date"]).dt.to_period("M").astype(str)
snap_cls = snap.set_index(snap["dex"] + ":" + snap["name"])["asset_class"]
hlc["asset_class"] = (hlc["dex"] + ":" + hlc["coin"]).map(snap_cls).fillna(hlc["coin"].map(classify))
g = hlc[hlc["asset_class"] != "crypto"].groupby(["month", "asset_class"])["notional_usd"].sum().reset_index()
g["venue"] = "hyperliquid-builder"
traj.append(g)
vo = vol_o.copy()
vo["month"] = pd.to_datetime(vo["date"]).dt.to_period("M").astype(str)
vo = vo.merge(ostp2[["pair_id", "asset_class"]], on="pair_id", how="left")
vo["asset_class"] = vo["asset_class"].replace(CLASS_MAP)
g = vo[vo["asset_class"] != "crypto"].groupby(["month", "asset_class"])["volume_usd"].sum().reset_index()
g = g.rename(columns={"volume_usd": "notional_usd"}); g["venue"] = "ostium"
traj.append(g)
for name, f, symcol in [("vest", "longtail/vest_daily_klines.parquet", "symbol"),
                        ("aster", "longtail/aster_daily_klines.parquet", "symbol")]:
    k = pd.read_parquet(RAW / f)
    k["asset_class"] = k[symcol].map(classify)
    if name == "aster":
        rwa_syms = set(pd.read_parquet(RAW / "longtail/aster_symbols.parquet").query("is_rwa")["symbol"])
        k = k[k["symbol"].isin(rwa_syms)]
    else:
        k = k[k["asset_class"] != "crypto"]
    k["month"] = pd.to_datetime(k["openTime"]).dt.to_period("M").astype(str)
    k["notional_usd"] = np.where(k["quoteVolume"] > 0, k["quoteVolume"], k["volume"] * k["close"])
    g = k.groupby(["month", "asset_class"])["notional_usd"].sum().reset_index()
    g["venue"] = name
    traj.append(g)
traj = pd.concat(traj, ignore_index=True)
traj.to_parquet(OUT / "monthly_rwa_volume_by_venue.parquet", index=False)

# ---------------------------------------------------------------- basis economics, top RWA assets
# Short-perp/long-spot carry = mean annualized funding received - hedge costs (reported separately).
top = fs[(fs["asset_class"] != "crypto") & (fs["n_obs"] > 24 * 20)].copy()
top["abs_ann"] = top["ann_funding_mean"].abs()
top = top.sort_values("abs_ann", ascending=False)
FEES = {  # round-trip taker cost of perp leg entry+exit, decimal (approx, base tiers)
    "hyperliquid": 2 * 0.00045, "vest": 2 * 0.0005, "aster": 2 * 0.00035, "paradex": 2 * 0.0003,
}
def venue_fee(v): return FEES.get(v.split(":")[0], 0.001)
top["perp_roundtrip_cost"] = top["venue"].map(venue_fee)
# breakeven horizon: days holding for mean funding to cover perp round-trip + IBKR-ish spot hedge 4bp rt
top["hedge_roundtrip_cost"] = 0.0004
top["days_to_breakeven"] = ((top["perp_roundtrip_cost"] + top["hedge_roundtrip_cost"])
                            / top["abs_ann"].replace(0, np.nan) * 365)
top.to_parquet(OUT / "basis_econ.parquet", index=False)

# ---------------------------------------------------------------- compact printout
pd.set_option("display.width", 250, "display.max_rows", 100, "display.float_format", lambda x: f"{x:,.4g}")
print("== 24h vol/OI by venue x class ==")
print(vbc.pivot_table(index="venue", columns="asset_class", values="vol_24h_usd", aggfunc="sum").fillna(0).round(0))
print("\n== OI by venue x class ==")
print(vbc.pivot_table(index="venue", columns="asset_class", values="oi_usd", aggfunc="sum").fillna(0).round(0))
nc = fs[fs["asset_class"] != "crypto"]
print("\n== funding stats: top 25 RWA by |ann funding|, >=20d history ==")
cols = ["venue", "symbol", "asset_class", "days_history", "ann_funding_mean", "ann_funding_last30d",
        "pct_hours_positive", "ann_p5_7d", "ann_p95_7d", "mean_abs_premium_bps"]
print(nc[nc["n_obs"] > 480].reindex(nc[nc["n_obs"] > 480]["ann_funding_mean"].abs().sort_values(ascending=False).index)[cols].head(25).to_string(index=False))
print("\n== RWA funding by venue x class (median of per-asset ann means, >=20d) ==")
print(nc[nc["n_obs"] > 480].groupby(["venue", "asset_class"])["ann_funding_mean"].agg(["median", "mean", "count"]).round(4))
print("\n== Ostium: effective per-side carry annualized by class (90d) ==")
print(ofs.groupby("asset_class")[["ann_eff_long_90d", "ann_eff_short_90d"]].median().round(4))
print("\n== basis: top 15 carry candidates ==")
print(top[["venue", "symbol", "asset_class", "ann_funding_mean", "ann_funding_last30d", "days_history", "days_to_breakeven"]].head(15).to_string(index=False))
print("\nwrote:", [p.name for p in sorted(OUT.glob('*.parquet'))])
