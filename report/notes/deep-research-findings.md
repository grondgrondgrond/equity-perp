# Deep-research findings: RWA perps landscape (collected 2026-07-11)

## Summary

The RWA perps sector has scaled explosively: monthly volume hit $347B in May 2026 (up ~1,472x from Jan 2025), with $1.32T processed YTD 2026 versus $104B in all of 2025 — though the aggregate is dominated by CEXs (Binance, MEXC), and single-stock equity perps specifically remain small ($34B/month, under 1% of TradFi stock volume, concentrated in NVDA/TSLA/MU). Among DEXs, Hyperliquid is the clear leader (19.8% of 2026 TradFi-perps share), and its HIP-3 builder markets are the only venue in scope offering a true central limit order book with unified API access — but deployment is capital-gated (500k HYPE, ~$30M staked) and each market's oracle price is set by the deployer, a material basis-trade risk. Ostium and gTrade are oracle-priced synthetic venues where a protocol vault is the universal counterparty: there is no order book to make markets on, no microstructure to read, and — critically for basis traders — Ostium's RWA pairs charge a one-sided rollover fee (floored at zero, paid to the vault) instead of two-sided funding, so classic funding-capture trades do not exist there; RWA markets also close with the underlying (orders queue, high-leverage stock positions auto-close before the bell). Net assessment for a small independent quant: taker-side short-horizon strategies and basis trades are most viable on Hyperliquid HIP-3 markets (order book, open access, real depth — XYZ100 reached $213M OI by March 2026), while Ostium/gTrade are viable only for directional/latency-style strategies against their oracles within OI caps, not for market-making or funding harvesting.

## Verified findings

### 1. [high confidence] Sector scale and growth: RWA perps monthly volume reached $347.17B in May 2026, ~1,472x growth from $0.23B in January 2025, and crypto exchanges processed over $1.32T in TradFi perps volume YTD 2026 versus $104.21B in all of 2025. The aggregate is CEX-dominated (Binance $498.66B and MEXC $323.86B over the 17-month window), so headline figures overstate the organically tradeable DEX liquidity relevant to an on-chain quant; MEXC volumes are widely suspected of inflation.

- Evidence: CoinGecko report (updated July 8, 2026) states verbatim: 'Perpetuals trading volume for RWAs has scaled exponentially by 1,472x from $0.23 billion at the start of 2025, to $347.17 billion in May 2026' and 'Exchanges have already processed over $1.32 trillion in TradFi perps volume this year to date, far beyond the $104.21 billion traded last year.' Corroborated by multiple independent outlets.
- Vote: 3-0 (two merged claims, both 3-0)
- Sources: https://www.coingecko.com/research/publications/tradfi-on-crypto-exchanges-report-2026

### 2. [high confidence] Hyperliquid is the leading DEX venue for TradFi/RWA perps: its share of TradFi perps volume grew from 6.0% average in 2025 to 19.8% in 2026 ($272.39B cumulative over Jan 2025–May 2026), ranking third overall behind CEXs Binance and MEXC.

- Evidence: Primary CoinGecko report states Hyperliquid processed $272.39B over the 17-month window with 6.0% average monthly share in 2025 rising to 19.8% in 2026, behind Binance ($498.66B) and MEXC ($323.86B). All figures match the source exactly; corroborated by secondary coverage.
- Vote: 3-0
- Sources: https://www.coingecko.com/research/publications/tradfi-on-crypto-exchanges-report-2026

### 3. [high confidence] Single-stock equity perps remain a small, concentrated niche: tokenized equity perps volume grew ~40x from $831.17M (July 2025) to $34.00B (May 2026), concentrated in Nvidia, Tesla, and Micron (Micron spiked 17x to $13.16B in May 2026; Circle also ranks top-3 on 2026 YTD volume), yet still under 1% of real-world stock market volume. Name concentration means quant capacity outside the top few tickers is limited.

- Evidence: Report states tokenized stocks grew 'by almost 40x to $34.00B in May 2026', names Nvidia/Tesla/Micron as most widely traded, notes Micron's $736.21M→$13.16B April-to-May spike, and that this makes up 'less than 1% of total trading volume on TradFi stock markets.' Corroborated by cryptobriefing.com and others.
- Vote: 3-0
- Sources: https://www.coingecko.com/research/publications/tradfi-on-crypto-exchanges-report-2026

### 4. [high confidence] Hyperliquid HIP-3 deployment is permissionless in mechanism but capital-gated in practice: any deployer staking 500,000 HYPE (~$25–32M depending on price; must remain staked at least 183 days post-deployment) can launch a perp DEX, with the first 3 markets free and subsequent markets allocated via a 31-hour Dutch auction (500 HYPE minimum). Deployers face validator slashing of up to 100% of stake for harming the network. Practical consequence: RWA/equity perp markets on Hyperliquid are operated by well-capitalized builder firms (or pooled-stake vehicles like Kinetiq Launch), not small independents — but trading them is open to anyone.

- Evidence: Official Hyperliquid docs: 'The staking requirement for mainnet will be 500k HYPE... maintained for a minimum of 183 days after the dex is deployed'; first 3 assets need no auction; HIP-3 auctions share HIP-1 hyperparameters (31-hour Dutch auction, 500 HYPE floor); slashing 'up to 100%' for the most severe harm tier. HYPE ~$65-68 in July 2026 puts the stake near $32M. Merges three unanimous claims (500k stake/auction/slashing; capital barrier; permissionless mechanism).
- Vote: 3-0 (three merged claims, all 3-0)
- Sources: https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-3-builder-deployed-perpetuals, https://www.falconx.io/newsroom/the-transformational-potential-of-hyperliquids-hip-3, https://dune.com/yandhii/hip3

### 5. [high confidence] HIP-3 market mechanics: builder-deployed equity/RWA perps trade on Hyperliquid's native HyperCore central limit order book with unified API access (same trading API as core perps) — genuine order-book microstructure, not a vAMM. However, the deployer itself sets oracle prices, leverage limits, and market settlement (setOracle ~every 3 seconds), so the price feed is deployer-operated rather than validator-sourced; mitigations include 1%-per-tick markPx clamps, 10x start-of-day clamps, and mandatory validator review on >50% intraday moves. Deployer oracle risk is a first-order consideration for basis trades on these markets.

- Evidence: Docs verbatim: 'HIP-3 inherits the HyperCore stack including its high performance margining and order books... the API to trade HIP-3 perps is unified with other HyperCore actions' and deployer responsibilities include 'Market operation, including setting oracle prices, leverage limits, and settling the market if needed.' Corroborated by Jsquare, Datawallet, HypeRPC, OAK Research.
- Vote: 3-0 (two merged claims, both 3-0)
- Sources: https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-3-builder-deployed-perpetuals

### 6. [high confidence] HIP-3 markets have demonstrated real, growing liquidity: the first market, Unit's XYZ100 (equity-index-style), had over $80M daily volume and $70M open interest by Oct 28, 2025 (deployer earned $100K+ in fees in under 2 weeks); by March 2026, XYZ100 OI had grown to ~$213M and total builder-deployed market OI exceeded $1.2B — sufficient depth for a small independent quant's strategies.

- Evidence: FalconX article states verbatim the $80M daily volume / $70M OI figures as of Oct 28, 2025; verifier independently corroborated via The Defiant (~$72M 24h volume, $55M OI same period) and CoinDesk March 2026 ($213M XYZ100 OI, $1.2B+ builder-market OI). FalconX has ecosystem exposure but on-chain figures are verifiable.
- Vote: 3-0
- Sources: https://www.falconx.io/newsroom/the-transformational-potential-of-hyperliquids-hip-3

### 7. [medium confidence] Ostium scale and asset mix: $45B+ cumulative volume (independently ~$59.7B on DefiLlama by July 2026) across 55 listed markets as of April 2026 (22 single stocks incl. NVDA/TSLA/AAPL/MSFT/GOOGL/META/AMZN/COIN, 7 equity indices incl. S&P 500/Nikkei/Hang Seng/FTSE, 7 commodities/metals, 8 FX, 2 ETFs, 9 crypto; expanded to ~71 instruments by July 2026), with over 95% of open interest in traditional (non-crypto) markets. Ostium is the purest-play RWA perps DEX in the scope.

- Evidence: Stork case study (Apr 3, 2026) states '$45B+ total trading volume... 55 markets listed... Over 95% of open interest sits in traditional markets' with an exact asset-class table. Volume corroborated by DefiLlama (~$59.7B) and Grvt ($50B+); ~91% of 30-day volume in non-crypto pairs per MEXC data. Caveat: Stork is Ostium's oracle vendor and the 95% OI figure originates in Ostium press materials; asset counts are April-2026-dated. Volume claim voted 2-1, asset-mix claim 3-0.
- Vote: 2-1 and 3-0 (merged)
- Sources: https://www.stork.network/case-studies/ostium-rwa-custom-oracle

### 8. [high confidence] Ostium market structure: fully oracle-priced synthetic perps with no order book — all open/close orders fill against the latest oracle-reported price (plus dynamic spread), with an on-chain USDC vault (OLP) acting as universal counterparty/market maker; there is no designated external MM firm intermediating flow, and no maker opportunity or on-venue microstructure for a quant. RWA feeds are a purpose-built three-layer pipeline (multiple providers running Ostium's proprietary pricing algorithm → Stork-operated custom aggregator → pull-based on-chain subscriber) with per-feed market-hours enforcement, holiday calendars, and gap-risk-aware pricing at open; crypto pairs use Chainlink low-latency feeds. Liquidations and conditional orders (SL/TP/limit) are executed by third-party keeper networks (Gelato, plus Chainlink Automation in newer docs), not the protocol itself — liquidation timing depends on keeper responsiveness.

- Evidence: Merges six claims (five unanimous, one 2-1). Ostium docs verbatim: 'Stork nodes for Ostium's in-house RWA feeds, Chainlink for crypto feeds'; 'Gelato automates the conditional orders for SL, TP, Liquidation and Limit'; 'all open and close orders are executed using the latest price'; 'Vault: on-chain liquidity pool that serves as the market maker for trades.' Stork case study details the three-layer oracle pipeline. Newer docs.ostium.com confirms Chainlink Automations co-executes with Gelato and that 'Neither Ostium Labs nor the protocol controls execution.'
- Vote: 3-0 (five claims) + 2-1 (one claim)
- Sources: https://ostium-labs.gitbook.io/ostium-docs/supporting-infrastructure/overview, https://ostium-labs.gitbook.io/ostium-docs/getting-started/ostium-explained-for-traders, https://www.stork.network/case-studies/ostium-rwa-custom-oracle

### 9. [medium confidence] Ostium funding regime — no classic funding-basis trade on RWA pairs: crypto pairs have periodic long/short funding based on OI imbalance (zero-sum between traders), but non-crypto pairs (equities/metals/FX/indices) instead charge a rollover fee reflecting underlying market carry costs, paid into the vault (SSL), updated daily via keeper automation. With the default isNegativeRolloverAllowed=false, rollover is floored at zero — traders never receive it — so two-sided funding-capture/basis-harvest strategies do not exist on Ostium's equity and metals perps in the current configuration.

- Evidence: Docs verbatim: crypto pairs have 'a funding payment periodically transfers between longs and shorts based on open-interest imbalance'; non-crypto pairs incur 'a rollover fee that reflects underlying market costs (paid into the SSL).' Rollover Fees section confirms daily T+1 updates, per-block compounding, and zero floor under default config; negative-rollover payouts may be enabled in a future phase. Vote was 2-1.
- Vote: 2-1
- Sources: https://ostium-labs.gitbook.io/ostium-docs/getting-started/ostium-explained-for-traders

### 10. [high confidence] Ostium market-hours handling: non-crypto markets follow the underlying market's open/close schedule (US stocks Mon-Fri 9:30 AM-4:00 PM ET) — no weekend/overnight stock trading. Limit/stop orders queue while closed and execute on reopen (market orders rejected outside hours), and stock positions above 10x leverage are auto-closed at 3:45 PM ET, 15 minutes before the close, eliminating overnight gap exposure at high leverage but also forcibly truncating positions.

- Evidence: Docs verbatim: 'Non-crypto markets follow regular open/close schedules; limit/stop orders queue when markets are closed and execute on reopen... Higher intraday leverage auto-closes before the bell; overnight leverage is lower.' Corroborated by Ostium's Stocks: Day Trading page (>10x auto-close at 3:45 PM ET) and an Aug 2025 GlobeNewswire release on 0DTE perps with up-to-100x intraday leverage.
- Vote: 3-0
- Sources: https://ostium-labs.gitbook.io/ostium-docs/getting-started/ostium-explained-for-traders

### 11. [high confidence] gTrade (Gains Network) market structure: fully synthetic, oracle-priced quoting with no order books — all pairs draw shared liquidity from gToken vaults, and trader PnL settles against those vaults rather than through order matching (pricing via a custom Chainlink DON returning median cross-exchange spot per order). Maximum open interest is capped both per pair and per group of correlated pairs (dynamically adjusted), bounding the size a basis or stat-arb trader can deploy on any single RWA market. The v10 upgrade (Aug 2025) kept the vault-counterparty model; no order-book migration is planned.

- Evidence: Docs verbatim: 'no order books or liquidity for each pair... gToken vaults provide shared liquidity for all listed trading pairs'; 'Maximum open interest is capped per pair and per group of correlated pairs. These limits help manage risk for liquidity providers.' Stocks/indices relisted since May 2025 and live as of July 2026. Note: a stronger claim that the Chainlink DON is the venue's SOLE price-feed source was refuted (1-2), so the exclusivity qualifier is dropped here.
- Vote: 3-0 (two merged claims, both 3-0)
- Sources: https://docs.gains.trade/gtrade-leveraged-trading/overview

### 12. [medium confidence] Viability synthesis for a small independent quant: (a) Hyperliquid HIP-3 markets are the most viable venue in scope — open CLOB access via the standard Hyperliquid API, demonstrated depth ($1.2B+ builder-market OI by Mar 2026), and standard perp funding mechanics — with the caveat that mark/funding prices are deployer-operated oracles subject to clamps and slashing-backed integrity rather than validator consensus. (b) Ostium and gTrade permit only taker-side, oracle-referenced strategies: no market-making, no order-flow signals, OI caps bounding size, and on Ostium no receivable funding on RWA pairs — so 'basis trades against retail-driven mispricings' there reduce to directional bets against the vault at oracle price plus spread, competing with the venue's own dynamic-spread and keeper mechanics. (c) Deploying one's own HIP-3 market is out of reach (~$30M stake) but unnecessary for trading.

- Evidence: Synthesis across confirmed claims 4-17: HIP-3's CLOB + unified API + open trading access versus Ostium/gTrade's vault-counterparty oracle-execution models with OI caps, zero-floored RWA rollover (Ostium), and market-hours restrictions. This is an inference from verified structural facts rather than a directly sourced claim, hence medium confidence.
- Vote: synthesis (derived from unanimous structural claims)
- Sources: https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-3-builder-deployed-perpetuals, https://ostium-labs.gitbook.io/ostium-docs/getting-started/ostium-explained-for-traders, https://docs.gains.trade/gtrade-leveraged-trading/overview, https://www.falconx.io/newsroom/the-transformational-potential-of-hyperliquids-hip-3

