"""Basis-trade compression analysis: monthly funding by name/venue and by hedgeability bucket.

Tests the 'funding has compressed as basis desks arrived' narrative against the panels.
Buckets xyz names by how easily a desk can hedge them:
  easy = US megacap/liquid futures (NVDA, MSFT, GOLD, CL, SP500...)
  hard = Korean/Japanese listings, synthetic indices (DRAM/H100/XYZ100), pre-IPO, meme smallcaps
  mid  = everything else (US mid-caps etc.)

Outputs: data/processed/funding_monthly_by_name.parquet,
         data/processed/funding_monthly_by_bucket.parquet
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data/raw", ROOT / "data/processed"
ANN = 8760

EASY = {"NVDA","MU","META","MSFT","GOOGL","AAPL","AMZN","TSLA","AVGO","INTC","QCOM","NFLX",
        "LLY","COST","ORCL","AMD","SP500","GOLD","SILVER","CL","BRENTOIL","COIN","MSTR","PLTR",
        "HOOD","TSM","SMH","XLE","SNDK","WDC","MRVL","DELL","CRCL","ARM","ASML","NOW","IBM"}
HARD = {"SKHX","SKHY","SMSN","HYUNDAI","KIOXIA","IBIDEN","SOFTBANK","DRAM","H100","XYZ100",
        "PURRDAT","SHAZ","SPCX","GIGADEV","MINIMAX","ZHIPU","CBRS","STRC","BOT","QNT","USAR",
        "KR200","JP225","NIFTY","IBOV","BIRD","BE"}

frames = []
hl = pd.read_parquet(RAW / "hyperliquid/funding_history.parquet")
hl = hl[hl.dex == "xyz"].copy()
hl["venue"], hl["symbol"], hl["hourly_rate"] = "hyperliquid:xyz", hl["coin"].str.replace("xyz:", "", regex=False), hl["fundingRate"]
frames.append(hl[["venue", "symbol", "time", "hourly_rate", "premium"]])
e = pd.read_parquet(RAW / "longtail/extended_funding_history.parquet")
e["venue"] = "extended"
e["symbol"] = e["market"].str.replace("_24_5-USD", "", regex=False).str.replace("-USD", "", regex=False)
e["hourly_rate"], e["premium"] = e["fundingRate"], np.nan
frames.append(e[["venue", "symbol", "time", "hourly_rate", "premium"]])
a = pd.read_parquet(RAW / "longtail/aster_funding_history.parquet").sort_values(["symbol", "fundingTime"])
iv = a.groupby("symbol")["fundingTime"].diff().dt.total_seconds().div(3600)
a["ivh"] = iv.groupby(a["symbol"]).transform("median").fillna(8).clip(1, 24)
a["venue"], a["hourly_rate"], a["premium"] = "aster", a["fundingRate"] / a["ivh"], np.nan
a["symbol"] = a["symbol"].str.replace("USDT", "", regex=False)
a = a.rename(columns={"fundingTime": "time"})
frames.append(a[["venue", "symbol", "time", "hourly_rate", "premium"]])
v = pd.read_parquet(RAW / "longtail/vest_funding_history.parquet")
v["venue"] = "vest"
v["symbol"] = v["symbol"].str.replace("-USD-PERP", "", regex=False)
v["hourly_rate"], v["premium"] = v["oneHrFundingRate"], np.nan
frames.append(v[["venue", "symbol", "time", "hourly_rate", "premium"]])

f = pd.concat(frames, ignore_index=True)
f["time"] = pd.to_datetime(f["time"], utc=True)
f["month"] = f["time"].dt.tz_localize(None).dt.to_period("M").astype(str)
f["bucket"] = np.where(f["symbol"].isin(EASY), "easy", np.where(f["symbol"].isin(HARD), "hard", "mid"))

byname = (f.groupby(["venue", "symbol", "bucket", "month"])
          .agg(ann_funding=("hourly_rate", lambda s: s.mean() * ANN),
               mean_abs_premium_bps=("premium", lambda s: s.abs().mean() * 1e4),
               n_obs=("hourly_rate", "count")).reset_index())
byname.to_parquet(OUT / "funding_monthly_by_name.parquet", index=False)

xyz = f[f["venue"] == "hyperliquid:xyz"]
bybucket = (xyz.groupby(["bucket", "month"])
            .agg(ann_funding=("hourly_rate", lambda s: s.mean() * ANN),
                 mean_abs_premium_bps=("premium", lambda s: s.abs().mean() * 1e4),
                 n_names=("symbol", "nunique")).reset_index())
bybucket.to_parquet(OUT / "funding_monthly_by_bucket.parquet", index=False)

pd.set_option("display.width", 250, "display.float_format", lambda x: f"{x:,.1f}")
print("xyz ann funding % by month x hedge bucket:")
print((bybucket.pivot(index="month", columns="bucket", values="ann_funding") * 100).round(1))
print("\nxyz |premium| bps by month x bucket:")
print(bybucket.pivot(index="month", columns="bucket", values="mean_abs_premium_bps").round(1))
mm = byname[byname.symbol.eq("MU")].pivot_table(index="month", columns="venue", values="ann_funding") * 100
print("\nMU ann funding % by venue (cross-venue spread):")
print(mm.round(1))
