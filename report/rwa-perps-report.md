# RWA / Equity Perps: State of the Space & Trading Feasibility

**Date of record: 2026-07-11** (Saturday — live snapshots reflect weekend conditions; equity oracles pinned at Friday 2026-07-10 close). All quantitative claims below are computed from data saved in `data/raw/` and `data/processed/` (see Data Dictionary, §7) unless a web source is cited. Qualitative claims were adversarially fact-checked (3-vote verification); sources in `report/notes/`.

---

## 0. TL;DR

- **The space is real and growing fast, but it is effectively one venue.** Hyperliquid HIP-3's `xyz` dex (trade[XYZ], operated by Unit) does **$3.1B/day** in RWA perp volume — as much as Hyperliquid's entire main crypto dex — and grew from $0.76B/mo (Oct 2025) to **$85B/mo (Jun 2026)**. Everything else on-chain is 1.5–3 orders of magnitude smaller: Extended ~$110M/day TradFi, Aster RWA ~$52M/day, Ostium ~$47M/day, Vest ~$24M/day; Avantis/gTrade/Paradex equity books are near-dead.
- **xyz is the only venue with a real order book open to anyone.** Jump, Selini, and Wintermute already quote it voluntarily; there is no designated-MM moat. Ostium/gTrade/Avantis/Vest are oracle-priced vault-counterparty models — nothing to make markets on, taker-only.
- **First-order funding capture is genuinely there on xyz**, concentrated in hot names: measured long-run funding +65% ann (SK Hynix), +35% (DRAM index), +15% (MU), +11% (NVDA), −16% (crude). A naive threshold rule (enter >20% ann trailing funding, exit <5%, net of fees) earned **25–90% ann on deployed notional** in the dislocating names, 45–70% time in market. Realistic capacity: single-digit $M per name before you are a visible share of OI.
- **Ostium is rationally priced** (carry = SOFR pass-through, uniform 5.45% long-pays across all stocks) despite 90%+ long retail OI — the interesting trade there is not funding capture but the fact that a deeply retail-long book never pays shorts more than ~1.4%.
- **Recommendation (§6):** a small-scale build is feasible and worth doing, sequenced as (1) funding/basis harvest on xyz with off-exchange hedge, (2) short-horizon overnight/weekend price-discovery trades perp-vs-next-open, (3) only then quoting/stat-arb. Budget for the two structural risks that don't exist in normal equity quant: deployer-controlled oracles and 24/7 trading of assets whose hedge only trades 6.5 hours a day.

---

## 1. Market landscape and sizing

### 1.1 Sector scale

CoinGecko's July 2026 report (verified 3-0): RWA perps volume across all crypto venues hit **$347B/month in May 2026**, ~1,472x from Jan 2025; $1.32T YTD 2026 vs $104B in all of 2025. Caveats: the aggregate is CEX-dominated (Binance $499B, MEXC $324B cumulative over 17 months; MEXC widely suspected of inflation), and **single-stock equity perps specifically are only ~$34B/month (May 2026)** — under 1% of TradFi cash-equity volume — concentrated in NVDA, TSLA, MU (and CRCL on 2026 YTD).

### 1.2 On-chain venue league table (our data)

| Venue | RWA vol 24h (Sat) | RWA vol trend (monthly) | RWA OI | Model | Status |
|---|---|---|---|---|---|
| **HL xyz (trade[XYZ])** | $3.08B | $0.76B (Oct-25) → $23.7B (Jan-26) → **$85.2B (Jun-26)** | $3.62B (ATH on 7/10) | CLOB | The market |
| **Extended (TradFi)** | **$110M** ($66M stocks, $29M metals) | growing (equities `_24_5` listings ramping since Q1-26) | $43M | CLOB (Starknet) | **#2, underrated** |
| **Aster RWA** | $52M (116 RWA perps incl. pre-IPO OPENAI/ANTHROPIC/SPCX) | ~$1.45B/30d; off Mar-26 peak | n/a | CEX-style book | #3, declining |
| **Ostium** | $25M (closed mkts; ~$47M/d 30d avg) | $2.2–5.2B/mo since Nov-25; peaked Feb-26, Jun $1.78B | $200–285M | Oracle+vault | #2 by OI, cooling |
| **Vest** | $24M (515 stock perps listed, 74 trading Sat) | ~flat ($182M/30d); OI growing $28M→$76M | $45M | zkRisk pool | small, alive |
| **Helix (Injective)** | small | n/a | n/a | CLOB | 22 TradFi perps, funding-capped |
| **HL mkts (Kinetiq)** | $3.9M | fading | $2.1M | CLOB | marginal |
| **Avantis (equities)** | n/a (plat. $86M/d) | platform −54% over 6mo | $1.2M equity | Oracle+vault | dead-ish equities |
| **gTrade (equities)** | n/a | platform −72% over 6mo | **$45k** equity | Oracle+vault | dead equities |
| **Paradex RWA** | ~$50k (18 RWA mkts, listed Jun-26) | embryonic | ~$0.4M | CLOB | negligible so far |
| Dead HIP-3 dexes | — | — | — | — | Ventuals, Felix, dreamcash*, km, abcd |

*dreamcash: Tether-invested, Selini as designated LP, but OI $67M→$24M→0 in the DefiLlama fee series; the HL API shows all its markets delisted. Treat as dead despite the February press.

Sources: `data/processed/monthly_rwa_volume_by_venue.parquet`, `volume_by_class_24h.parquet`, `data/raw/defillama/*`, agent-verified DefiLlama page snapshots (per-protocol daily volume API was paywalled in Mar 2026; trajectory reconstructed from Wayback snapshots + live fees/OI series).

### 1.3 Concentration and asset-class mix (HL builder dexes, 24h)

- **By class:** single stock $2.04B vol / $1.97B OI (99 assets) · equity index $496M / $929M (44) · commodity $429M / $467M (20) · precious metals $102M / $214M (18) · FX $6.7M / $31M (7).
- **By name:** the memory-chip complex — SK Hynix (SKHX $632M + SKHY $321M), MU ($245M), SanDisk ($176M), DRAM index ($175M) — is **~half of xyz volume**. Then XYZ100 ($310M), SP500 ($147M), CL ($143M), SpaceX pre-IPO ($140M), META ($104M). Top-15 names ≈ 80% of RWA volume.
- **Ostium 30d by class:** equity index $555M (NDX alone $505M = 36% of platform), FX $189M, metals $149M, single stock $109M, commodity $95M. NDX OI $90M at 72% of its $125M cap, **99.8% long**.
- Volume follows the retail narrative of the month: MU/memory names spiked with the DRAM cycle, Micron did $736M→$13.2B/mo (Apr→May) across venues per CoinGecko. Capacity outside the top ~10 tickers is thin.

---

## 2. Funding rates and first-order strategy economics

All stats below computed from tick-level venue data: 356,676 hourly funding rows (HL, 180d), 289,914 (Vest, 185d), 34,976 (Aster, ~180d, 4–8h intervals), 21,609 pair-days (Ostium, 556d). Annualized = hourly × 8760 or daily × 365.

### 2.1 Long-run funding levels (measured)

**HL xyz (hourly funding, mean annualized over full history):**

| Asset | mean ann | last-30d ann | % hrs > 0 | mean abs premium |
|---|---|---|---|---|
| SKHX (SK Hynix) | **+64.6%** | +77.7% | 69% | 35 bp |
| SMSN (Samsung) | +38.5% | +52.1% | 62% | 35 bp |
| DRAM | +35.4% | +21.5% | 84% | 14 bp |
| MU | +15.4% | — | 86% | 9 bp |
| NVDA | +10.9% | — | 88% | 5.6 bp |
| SILVER | +10.0% | — | 88% | 5 bp |
| CRCL | +9.6% | — | 84% | 8 bp |
| META | +6.7% | — | 87% | 4.3 bp |
| SPCX (SpaceX) | +6.4% | — | 66% | 17 bp |
| XYZ100 | +1.8% | — | 72% | 3.5 bp |
| SP500 | −3.2% | — | 50% | 3.9 bp |
| CL / BRENTOIL | **−16.0%** | — | 64% | 13–14 bp |

Pattern: persistent retail long bias in narrative names (funding positive 70–90% of hours), near-zero on big indexes (SP500/XYZ100 are efficiently arbed), persistently **negative in crude** (perp trades under oracle — shorts crowd in, longs get paid; consistent with Ostium's backwardation carry pass-through).

**Venue medians (per-asset annualized means, RWA only):** xyz single stocks +10.4%, Aster metals +27%, Aster commodities +23%, Vest single stocks +5.0%, Aster single stocks +4.8%. Aster's metals/commodity funding is the richest per unit of listing, but its books are thin and declining.

**Ostium (per-side carry, 90d):** completely uniform across equities — **longs pay 5.45%, shorts receive 1.32%** (5.52%/−1.62% last 30d), indexes identical, gold 6.3%/−0.3%, USDJPY longs *receive* 1.15% / shorts pay 4.3% (rate differential), **crude: longs receive ~29–31%, shorts pay ~39–40%, with ±29% vol** (futures term-structure pass-through). Key structural fact (found on-chain; the public docs are stale): Ostium **migrated on 2025-10-19** from a zero-floored rollover to a per-side pays/receives regime — but the rate is set by external financing benchmarks, **not OI imbalance**, so the 90%+-long retail book does not blow out funding. There is no imbalance premium to harvest; the "edge" shorts earn is capped at ~1.3-1.6%.

### 2.2 High-frequency deviations (the tradeable part)

Persistence: hourly funding on xyz has AR(1) ≈ 0.5–0.85, deviation half-life **2–4 hours** in most names (MRVL 1h, COST 4.2h); Vest is much stickier (half-lives 7–31h — its zkRisk engine updates funding slowly); Aster 0.6–2h.

Frequency of dislocations (trailing-24h funding beyond ±20% annualized): SKHX 71% of hours (!), Hyundai 63%, GME 62%, LLY 62%, ASML 56%, MRVL 58%; broad xyz median ~30–45% of hours for single stocks vs ~5% for SP500/XYZ100. Premium dislocations concentrate in **names, not sessions**: liquid names hold 3–6bp mean |premium| even on weekends, while SKHX (KRW-priced) runs 27–53bp and GME widens to 27bp on weekends. |premium| > 25bp occurs 7% of hours (RTH) to 9.4% (weekends) across the top-12.

### 2.3 Naive funding-capture backtest (first-order basis trade)

Rule: when trailing-24h funding > +20% ann, short perp (hedge assumed price-neutral); exit < +5%; symmetric for negative. Costs: 2× taker (HL 4.5bp/side) + 4bp hedge round trip. Results on 180d history (`data/processed/funding_capture_backtest.parquet`):

| Market | side | trades/yr | avg hold | win rate | **net ann return on notional** | time in mkt |
|---|---|---|---|---|---|---|
| xyz:BIRD | short | 98 | 2.6d | 61% | **+92%** | 69% |
| xyz:HYUNDAI | short | 122 | 1.8d | 51% | +45% | 58% |
| xyz:GME | short | 70 | 4.2d | 69% | +44% | 80% |
| xyz:SKHX | short | 129 | 2.0d | 54% | +39% | 71% |
| xyz:URNM | short | 94 | 2.1d | 60% | +34% | 55% |
| xyz:NATGAS | short | 49 | 2.9d | 48% | +33% | 39% |
| aster:NATGAS | short | 8 | 40d | 100% | +68% | 92% |
| aster:EWY | short | 20 | 16d | 71% | +47% | 86% |
| vest:COIN | short | 6 | 2.8d | 67% | +68% | 4.5% |

**Read this honestly:** applied indiscriminately across *all* 67 xyz RWA names the rule is ~breakeven at the median (+1.1%; mean +9.3%, all of it from the tail); Aster median +11.6%, Vest +0.9%. The edge is **name-selective**: restricted to the dozen liquid dislocation-prone names above (SKHX/MU/GME/HYUNDAI/URNM/SMSN/MRVL/ASML…), the median is **+24%** and the 75th percentile +37%. Funding-level persistence (§2.1: the same names run hot for months) is what makes ex-ante selection plausible rather than hindsight. Further caveats:

- These are **funding-accrual-only** P&L on perp notional, assuming a perfect hedge. The perp trades 24/7; a cash-equity hedge only trades RTH (plus futures for indexes/metals/oil, which do cover most of the week). For single stocks the hedge gap is real: you carry overnight/weekend basis risk or hedge with a correlated 24/7 instrument. This is the central engineering problem of the whole space — and also its opportunity (§5).
- Double-counting warning: high-funding hours correlate with perp premium > 0; entering short at a premium adds to returns (you sell above oracle), so if anything the funding-only number is conservative on entry, but exits give some back.
- **Capacity:** BIRD/HYUNDAI/GME OI is $10–40M each; taking $1–3M notional per name across 10–15 names → $15–40M gross book is plausible before you're >5% of OI in the small names. SKHX/MU/NVDA can absorb far more ($200–500M OI each).
- xyz **HIP-3 fee caveat**: deployers may take a fee share on top of base taker fees; verify the live fee schedule per dex before sizing (not exposed in the public info API; check app or a small live order).

### 2.4 Cross-venue and perp-vs-real basis

- Same-name funding across venues is only weakly synchronized, and the overlap set is now wide: **TSLA, NVDA, MSTR, CRCL, HOOD, GOOGL, MSFT, META, INTC, MU, SNDK, SPCX, XAU, XAG each trade on 3–5 of {xyz, Extended, Aster, Vest, Paradex, Helix}**, ~12 of them with a Kraken xStocks spot print too. A long/short perp-vs-perp trade removes the cash-hedge problem entirely and is executable 24/7, at the cost of thin-side liquidity. Signals that agree everywhere (a sanity check on the data): CRCL/MSFT/META/ORCL longs pay 10–30%/yr on every venue that lists them; oil shorts pay 11–24%/yr everywhere; TSLA is flat-to-negative; silver/platinum strongly positive everywhere. The per-venue panels are in `funding_stats.parquet` (152 HL + 83 Vest + 22 Aster + 40 Extended + 18 Helix RWA symbols).
- Kraken xStocks (tokenized cash equities, `data/raw/kraken/`) trade 24/5 and could hedge weekday-overnight, but taker fees (~10–40bp tier-dependent) and thin books make them a poor systematic hedge; real utility is as an independent 24/5 price reference.

---

## 3. Platform deep-dives (mechanics you need to know)

### 3.1 Hyperliquid HIP-3 (`xyz` and friends) — the venue that matters

- **Structure:** builder-deployed perp dexes on HyperCore's native CLOB; margining, liquidation engine, and API identical to main-dex Hyperliquid (same order types, same liquidation waterfall: margin → backstop vault). Trading access fully permissionless.
- **Oracle risk (the big one):** the *deployer* (Unit, for xyz) sets oracle prices (~every 3s), leverage caps, and can settle markets. Guardrails: 1%-per-tick mark clamps, 10× start-of-day clamps, validator review on >50% intraday moves, and slashing of the deployer's 500k-HYPE (~$32M) stake. You are trading against an operator-controlled price feed with economic — not cryptographic — integrity guarantees.
- **DMM alignment:** no designated MM, no LP vault. On-chain attribution (ChainCatcher, Apr 2026) shows Jump Crypto ($3.15B), Selini ($1.03B), Wintermute ($230M) and large individuals quoting voluntarily. **Open to all; no rebate program found** — and no evidence Unit trades its own book.
- **Hours:** trades 24/7. Weekend equity hourly volume runs 6–18% of weekday (44–48% for crude); funding accrues all weekend against a frozen Friday-close oracle; mean |premium| widens 11→14bp. Prices genuinely move on Saturday (SKHX 1.1% intraday range with cash markets closed) — the book performs price discovery all weekend, then the oracle jumps to it (or doesn't) Monday 9:30.
- **OI caps:** per-asset "streaming" caps $20M–$1B (`dex_oi_caps.parquet`); non-binding for small-scale.
- **Churn risk:** xyz has already delisted 14 experiments (VIX, DXY, NIFTY, grains…); 5 of 9 builder dexes launched since Oct 2025 are dead. Assume any given listing can disappear with weeks of notice.

### 3.2 Ostium — pure-RWA #2, structurally taker-only

- Oracle-priced synthetic perps on Arbitrum; **no order book**. Counterparty = OLP vault (permissionless USDC deposits). Fills at oracle price + dynamic spread; fees 3bp (indexes/FX) to 6bp (stocks) per side; max leverage 100–200x intraday, 5–10x overnight for stocks; >10x stock positions **auto-close 3:45pm ET**; RWA markets closed = orders queue (no weekend equity trading at all).
- Oracle: proprietary 3-layer pipeline (multi-provider → Stork aggregator → pull-based on-chain); liquidations executed by Gelato/Chainlink keepers — timing not protocol-guaranteed.
- **MM alignment:** cap table is trading firms (Jump, GSR, SIG, Wintermute Ventures via $20M Series A, Dec 2025) but execution has no MM: the vault warehouses all delta. A "dynamic hedging engine" that would route delta to external MMs is announced but not live.
- **OI caps bind:** NDX 72% utilized, MU 53%, USDMXN 97%. Retail is >90% long in 30 of 39 active pairs.
- For a quant: no funding harvest (carry is rational, §2.1), no making, no microstructure. The residual angles are (a) latency race against the oracle at equity open/close (they defend with spread + gap-aware pricing at open — assume this is closed), (b) directional use of its uniquely long-skewed retail positioning data, which is public on-chain (`pair_daily_raw.parquet` has per-side OI history).

### 3.3 Vest — MM-firm project, slow-moving funding

Backed by Jane Street, QCP, Amber, Selini (2023–2025 rounds). No CLOB: zkRisk engine prices against an LP pool, zero trading fees. 83 RWA symbols with full 185d hourly funding history collected. Most active market: **SPCX (SpaceX pre-IPO)**; ~$25M/day platform volume, OI growing to ~$76M. Funding is sticky (half-life 7–31h) and mostly modest (median stock +5% ann) — occasional rich dislocations (COIN averaged +174% ann over its listing; ONDS trailing >20% ann 25% of the time). Thin, but the stickiness means when a dislocation appears you have hours-to-days to act, and zero fees make small basis clips cheap. The catch: you're trading against a pool priced by the house's risk engine — assume adverse selection is managed against you.

### 3.4 Aster — CEX-style books, explicit MM courtship

Binance-style API (`fapi.asterdex.com`), YZi-Labs-seeded. **116 RWA perps** (101 stocks incl. Asian names — Samsung, SK Hynix, Tencent, Xiaomi, Hyundai, Pop Mart — plus pre-IPO OPENAI/ANTHROPIC/SPCX, 10 ETFs, 9 commodities); RWA 24h $52M, 30d ~$1.45B (top: CL, SNDK, SKHYNIX, SPCX, XAU/XAG). Since Dec 2025 **makers pay zero fees and earn points on NVDA/TSLA**; open MM program (≥$100M/mo bar, hourly rebates, ~$300k/mo in ASTER). Funding intervals are mixed per symbol (8h stocks, 4h metals, 1h for ~a dozen actives — infer from timestamps) and rich on metals/commodities (XAG +29%, NATGAS +68%, MU +54%, SKHYNIX +34% mean ann) but RWA volume is well off its March peak. On Saturday the pre-IPO marks sat −70 to −94bp under their static index. Viable as a secondary venue for cross-venue funding spreads; watch for wash-inflated volume (its DefiLlama normalized-volume ≈ raw, which is reassuring, but the RWA books specifically are quiet).

### 3.5 Extended — the underrated #2 (order book, 24/5 equities)

Starknet-based CLOB (`api.starknet.extended.exchange`); 52 TradFi markets (19 equities with `_24_5` 24/5 trading, 7 commodities, index perps SPX500m/TECH100m, ~20 more pre-listed incl. AVGO/TSM/ASML/SKHYNIX, and one exotic: a SpaceX/Oracle pre-IPO *basket*). TradFi 24h volume **$109.5M / OI $43M** — bigger than Ostium on volume, second only to xyz — led by XAU $19M, SPX500m $13.5M, XAG $9M, SNDK $8M, MU $7M. Hourly funding, 185d collected: CRCL +23%, ORCL +22%, XPT +21%, XAG +19%, GOOG +13%, MSFT +11%, WTI **−24%**; AAPL/TSLA ~0. Our threshold backtest: profitable in the same name-selective way (XNG +40%, WTI long-side +22%, XPT +11%; median across all ~0). Max leverage 25x index, 10–17x equities. As a CLOB with real flow and no designated MM disclosed, this is the natural second venue after xyz for both funding capture and (eventually) quoting — and its 24/5 equities reduce (don't eliminate) the weekend hedge gap.

### 3.6 Helix / Injective — capped funding = permanent premium

22 TradFi perps (12 US equities, SPX, metals, EURUSD/USDJPY). Near-zero fees, but **hourly funding is hard-capped** (0.275bp/hr base, 0.55bp for MSTR/HOOD/COIN/CRCL, 6.25bp metals/SPX) and the cap **binds 43–98% of hours** in the big names — META funding sat at +cap 98.5% of observed hours (≈ +30% ann ceiling), TSLA pinned at −cap 43% of hours. A binding funding cap means the basis *cannot* be fully arbed to fair — persistent premium is structural. Volume is tiny, which is why this is a curiosity rather than a trade today, but it's the cleanest natural experiment in the dataset for "what retail pays when arb capital is absent." History only goes back to 2026-05-18 (indexer retention).

### 3.7 gTrade / Avantis — negative results (documented so you don't re-check)

- gTrade: 33 active stock pairs on Arbitrum but **$45k total stock OI**; borrowing fees imbalance-triggered (max 50–800% APR at full skew, currently ~0 at ~0 utilization). Equity product is dead.
- Avantis: 23 equity pairs incl. SPCX/CBRS pre-IPO, $1.2M equity OI vs $29M cap, always-on symmetric margin fees 5–30% APR (you pay both ways — negative carry for any basis position), 2–10x leverage only. Not investable for our purpose; the pre-IPO listings are the only notable feature.
- Paradex: platform volume collapsed −99% from January; its 18 RWA listings are weeks old (Jun 2026) and do ~$50k/day. Real listings, negligible flow — re-check in a quarter.

---

## 4. Designated market makers — summary answer

| Venue | Aligned MM? | Open access? |
|---|---|---|
| HL xyz | None designated; Jump/Selini/Wintermute quote voluntarily | **Fully open CLOB** — you can quote today |
| HL dreamcash | Selini designated LP (Tether-invested) | dead anyway |
| Ostium | None (vault is the MM; MM-heavy cap table; hedging engine "coming") | LP-open, no quoting |
| Vest | Jane St/QCP/Amber/Selini as *investors*; house risk-engine prices | no quoting |
| Aster | Open MM program with rebates; no disclosed firms | CEX-style, open |
| Extended | none disclosed | open CLOB |
| Kinetiq mkts | "strong MM relationships," unnamed | open CLOB, tiny |

The competitive read: **nobody has a structural monopoly on the only venue that matters (xyz)**. Incumbent crypto MMs are present but the microstructure is young (35bp premia persisting for hours in SKHX while Jump is active tells you they are capacity-constrained or uninterested in the long tail).

---

## 5. Feasibility assessment for a small-scale build

### 5.1 What the data says is real, ranked by evidence quality

1. **Funding/basis harvest on xyz (strong evidence, name-selective).** Persistent +10–65% ann funding in 10–20 names, dislocation half-lives of hours (you don't need speed), naive-rule net returns of +24% median / +37% upper-quartile on notional *in the selected liquid hot names* after fees (breakeven if sprayed across the whole universe — selection is the strategy). With $250k–$1M capital at 2–3x effective leverage, a 10–15 name short-perp book hedged off-exchange plausibly clears **15–30% net** before the tail risks below. This is the first thing to build.
2. **Perp-vs-perp cross-venue funding spreads (moderate evidence).** 14+ liquid names overlap across 3–5 venues (xyz/Extended/Aster/Vest); kills the hedge-hours problem; bounded by thin-side liquidity. Extended is the natural second leg (CLOB, $110M/day, 24/5 equities). Good second module reusing the same infrastructure.
3. **Overnight/weekend price-discovery trades (moderate evidence, biggest asymmetry).** xyz trades 24/7 against a frozen oracle; weekend premia widen (9.4% of hours >25bp) and Monday-open convergence is mechanical. Also the reverse: perp prices carry information — a 24/7 order book on TSLA is a free pre-market signal for a traditional equity quant book. Nobody hands out this dataset; you now have the collector for it.
4. **Retail-skew alpha / juicing a weak equity signal (speculative but structurally supported).** Ostium's per-pair long/short OI (99.8% long NVDA) and xyz funding are clean, public, real-money retail-positioning prints at hourly frequency. As a *feature* in a stat-arb/momentum model these are the kind of crowding signals that cost real money from alternative-data vendors. The mispricings (±20–50% ann funding ≈ ±5–15bp/day of drift between perp and fair) are large enough to add meaningful carry to a weak underlying signal traded *on the perp venue itself*.
5. **Market-making xyz longtail (needs more work).** Open book, no designated MM, wide persistent premia in the tail. But you'd quote against Jump/Selini/Wintermute with a deployer-controlled oracle. Only after months of taker-side data.

### 5.2 What kills you if ignored

- **Deployer oracle risk (xyz):** the price you're marked and liquidated on is set by Unit. Clamps + slashing bound but don't eliminate it. Sizing rule: nothing that can't wear a 1–3% adverse mark.
- **Hedge-hours mismatch:** single-stock perps accrue funding and move 24/7; your hedge doesn't. Weekend gap on a hot memory-chip name can be multiples of a week's funding. Mitigate with index/futures overlays, cross-perp hedges, and cutting single-name basis Friday afternoons.
- **Listing/venue churn:** 5 of 9 HIP-3 dexes died within 9 months; xyz delisted 14 tickers. Ostium volume is −65% from its Feb peak. Build venue-agnostic plumbing; assume any single market is ephemeral.
- **Regime youth:** every funding stat above comes from ≤6 months of history in a one-directional (DRAM-mania) tape. The +40% ann numbers are a bull-crowding artifact and will compress; the *mechanism* (retail crowding → funding) is what you're underwriting, not the level.
- **Not covered here:** US regulatory posture of trading equity perps, and venue/bridge custody risk. Both need a decision before real capital.

### 5.3 Recommended build path (small scale)

1. **Week 1–2:** turn `scripts/collect_*.py` into a scheduled pipeline (hourly funding/premium/OI snapshots; the collectors are already rerunnable). Paper-trade the §2.3 rule with live data; verify xyz all-in taker fee + any deployer fee share with small live orders.
2. **Week 3–6:** deploy the funding-harvest book on 5–10 xyz names with CME/index-futures overlay hedging (IBKR), single-name cash hedges RTH-only, flat single-name basis over weekends. Target: survive two funding regime flips, measure realized slippage vs the 4.5bp assumption.
3. **Month 2–3:** add cross-venue (Vest/Aster) funding spreads and the weekend→Monday-open convergence trade; start logging the order book (L2) on xyz for the eventual making/stat-arb decision.
4. **Kill criteria:** xyz RWA volume < $500M/day sustained, funding medians compressing under 5% ann across the board, or an oracle incident without validator response.

---

## 6. Answers to the four questions, in one place

1. **Volumes/growth/concentration/breakdown:** §1.2–1.3. One dominant venue (xyz, $3.1B/day, 8x growth in 8 months), then Extended ($110M/day, growing), Aster ($52M, declining), Ostium ($47M/day 30d avg, index/FX-heavy, cooling), Vest ($24M, flat). Single stocks ≈ 60% of xyz volume, memory-chip complex ≈ half; indexes ≈ 15%; metals ≈ 3–5%.
2. **Funding & basis economics:** §2. Long-run: +5–65% ann in crowded stocks, ~0 in big indexes, −16% crude, Ostium uniform 5.45%/−1.3% carry. HF deviations: 2–4h half-lives, ±20% ann breaches 30–70% of hours in hot names; naive capture nets +15–45%/yr on notional in size-relevant names.
3. **DMMs:** §4. No venue in the space is MM-captured; xyz is fully open with voluntary incumbent quoting; Vest is the most house-aligned (Jane Street et al. as investors, house risk engine); Aster has an open rebate program.
4. **Mechanics gotchas:** §3. Deployer-set oracles + clamps (xyz), 24/7 trading vs RTH hedges, Ostium's 3:45pm auto-close / order-queuing / per-side carry migration (docs are stale — trust the chain), keeper-driven liquidations on synthetic venues, binding OI caps on Ostium, venue/listing churn everywhere.

---

## 7. Data dictionary (what's saved, `data/`)

**raw/hyperliquid/** — `perp_dexs`, `dex_oi_caps`, `asset_ctx_snapshot` (457 assets, all dexes, classed), `funding_history` (356,676 rows: dex, coin, hourly time, fundingRate, premium; 180d xyz / 90d others), `daily_candles` (19,087 rows since xyz launch 2025-10-13, incl. notional), `hourly_candles_top` (top-15 xyz, 30d).
**raw/ostium/** — `pairs_snapshot` (75 pairs: classes, leverage, OI/caps/util, fees), `funding_history` + `daily_volume` (21,609 pair-days each, 2025-01-01→now; per-side funding+rollover daily fractions), `pair_daily_raw` (underlying cumulative snapshots incl. per-side OI history).
**raw/longtail/** — `gains_pairs_snapshot` (1,446 = 482 pairs × 3 chains), `avantis_pairs_snapshot` + 5 daily history tables (366d), `aster_{symbols,ticker24h,premium_index,funding_history(34,976; mixed 1/4/8h intervals),daily_klines}`, `vest_{symbols,ticker24h,ticker_latest,funding_history(289,914 hourly),daily_klines}` (NB: Vest API moved to `server-prod.hz.vestmarkets.com`, needs `xrestservermm` header), `extended_{markets(147),funding_history(104,052 hourly),daily_candles}`, `helix_{markets(284),funding_history(22,276 hourly, capped, since 2026-05-18)}`, `paradex_{markets,summary,funding_history,klines_1h}`.
**raw/kraken/** — xStocks pairs/tickers/daily OHLC (spot reference).
**raw/defillama/** — `daily_volume_by_protocol` (98,564 rows, 187 protocols, →2026-03-01), `perps_page_snapshots` (5 checkpoints →Jun-18), `daily_{fees,open_interest}_by_protocol` (live →now), overviews.
**processed/** — `funding_stats` (+ `_ostium`), `funding_rolling7d`, `deviation_stats`, `funding_capture_backtest`, `premium_by_session`, `volume_by_class_24h`, `monthly_rwa_volume_by_venue`, `basis_econ`.

Rebuild: `.venv/bin/python scripts/collect_*.py` then `scripts/build_processed.py`, `scripts/analyze_deviations.py`. Everything is local parquet (total ~10MB — S3 unnecessary at this size).

**Qualitative sources:** `report/notes/deep-research-findings.md` (12 adversarially-verified claims with URLs), `report/notes/mm-alignment.md` (dated, per-claim sources).

---

## 8. Addendum (2026-07-11): build-vs-deposit, and fading liquidations

### 8.1 What can be deposited vs what must be built

Live deposit products (verified same-day, details + sources in `report/notes/vault-products.md`): Ostium OLP $35M TVL, 4.2%/6.0%/7.1% realized APY (1mo/3mo/lifetime), max DD −7.4%, post-redesign gets 30% of open fees with a PnL buffer in front; Avantis avUSDC $29M at 8.5%; Gains gUSDC $7.4M at 3.6–7.5%; Vest LP dead ($0.76M, points only); Hyperbeat wVLP $2.9M (only live "LP a HIP-3 deployer" product); HLP $256M at 15–30% but crypto-only.

Structural facts: **no delta-neutral RWA funding-harvest vault exists** (Ethena only *proposed* equity-perp basis to its risk committee, Apr 2026); **Hyperliquid legacy user vaults cannot trade HIP-3 perps** (validator-operated markets only; the CoreWriter/HyperEVM vault standard will change this), so the xyz funding trade has no depositable wrapper and no copy-vault. Pendle Boros trades BTC/ETH funding fixed-vs-floating; equity legs (NVDA first) are reported but unconfirmed — if they ship, Boros becomes the one way to short equity-perp funding without building a hedge leg.

Conclusion: deposits buy 4–10% house-side beta with counterparty tail risk; ~all of the §5.1 alpha is build-only. Build sizing: collectors exist (this repo); venue connectivity is days each (HL python SDK, Aster is Binance-API-compatible, Extended/Ostium have SDKs); the real work is the hedge leg + 24/7 risk engine (IBKR/CME micros, margin on both sides, weekend policy) ≈ 2–4 weeks solo. Market timing note: Tiger Research (Q2 2026) reports tokenized-stock-perp funding already compressing to high single digits as basis desks arrive — matches our last-30d vs full-history compression in several names. The window is narrowing, not closed.

### 8.2 Fading liquidations

Where it can exist at all: only CLOB venues (xyz, Extended, Aster). Ostium/gTrade/Avantis liquidate against the vault at oracle price — zero market impact, nothing to fade (Ostium's 3:45pm ET >10x auto-close is predictable forced flow, but also vault-absorbed).

xyz mechanics shape the trade: liquidations trigger on oracle-anchored, clamped mark prices. With the oracle frozen off-hours, book moves don't cascade equity liquidations on weekends; forced flow concentrates at the cash open when the oracle gaps to the real print and crowded 20–40x longs are margin-called in a burst. The schedulable version: fade the open-print overshoot after weekend/overnight gaps in crowded-long names.

Empirical proxy (`scripts/analyze_reversals.py`, 30d hourly, top-15 xyz): after |1h move| > 1%, next-hour reversal averages **+24bp overnight (t=3.8, n=806), +27bp weekends (+36bp over 3h)** vs **−18bp continuation during RTH**; moves >3% revert +32bp. Round-trip taker ≈ 9bp. Off-hours flow-driven moves are fadeable at 2–4x cost coverage; fading RTH moves is negative (that's news). Caveats: 30-day single-regime sample, no true liquidation labels — production needs the live trade/L2 feed logged for a few weeks (liquidation attribution via HL node data or third-party trackers).
