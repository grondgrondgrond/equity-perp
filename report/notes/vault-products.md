# Passive exposure to RWA-perp inefficiencies: deposit products as of 2026-07-11

Research date: 2026-07-11. Yields/TVL pulled same-day from DefiLlama APIs (`yields.llama.fi/pools`, `api.llama.fi/tvl/*`) unless otherwise dated. "Live" = deposits open with nonzero TVL today.

## Headline answer

- **A true "Ethena for equity perps" does NOT exist yet as a retail deposit product.** Ethena itself has only *proposed* equity/commodity perp basis to its risk committee (Apr 6, 2026, Bankless); not approved or deployed. What exists today for equity-perp inefficiency exposure is (a) **house-side LP vaults** on RWA-perp venues (Ostium OLP, Avantis, Gains, Vest, Ventuals VLP), (b) **Hyperliquid user vaults** — but legacy vaults *cannot* trade HIP-3 markets, so xyz-basis copy-vaults are only just becoming possible via HyperEVM/CoreWriter vaults, and (c) **Pendle Boros** funding-rate markets (BTC/ETH live on Hyperliquid; equity-perp funding markets like NVDA reported/announced, not confirmed live).
- Crypto-basis synthetic dollars (Ethena sUSDe 3.9%, Falcon sUSDf 5.1%, Neutrl, Resolv, Liminal xHYPE 7.7%) are live but **crypto-funding**, not RWA/equity funding.

## Product table

| Product | Type | Venue exposure | TVL (2026-07-11) | Current / realized yield | How it earns | Retail? | Risks noted |
|---|---|---|---|---|---|---|---|
| **Ostium OLP** | House-side LP (RWA perps: FX, metals, indices, stocks) | Ostium (Arbitrum) | Protocol TVL $65.1M (llama); OLP vault ~$35M, down from $68M peak (tradingstrategy.ai) | 1-mo 4.2% APY, 3-mo 6.0%, lifetime 7.1% APY; recent app-quoted 7d APRs have run higher (37% during Jan-2025 growth spurt, per Ostium tweet 2025-01) | Post-2025 redesign: 30% of opening fees only; buffer absorbs trader PnL first. If c-ratio <100% (buffer wiped), OLP is direct counterparty to net trader PnL | Yes, permissionless USDC deposit | Lifetime max drawdown **-7.4%** (OLP took trader-PnL hits pre-redesign when RWA traders won big, e.g. gold rallies); tail risk = buffer depletion → direct PnL warehousing |
| **Avantis unified LP (avUSDC)** | House-side LP, formerly junior/senior tranches (merged Oct 2025, ~$90M at merge) | Avantis (Base) — crypto + FX + commodities perps | $29.2M (DefiLlama pool) | **8.5% APY now, 9.8% 30d avg** (DefiLlama, 7-day rolling basis) | Trading fees + counterparty to trader PnL (loss-protection tiers replaced tranches) | Yes | Trader-PnL exposure; TVL well off the $90M merge figure |
| **Gains gTokens (gUSDC etc.)** | House-side LP | Gains Network (Arbitrum/Base/Polygon) — crypto, FX, stocks perps | gUSDC Arb $7.4M, Base $1.1M | Arb gUSDC 3.6% now / 7.5% 30d avg; Base 2.3%/3.4% (DefiLlama) | Fees + counterparty to net trader PnL (gToken price can go <1) | Yes | Long history of trader-win drawdown epochs; stock-perp exposure included |
| **Vest LP** | House-side LP (zkRisk AMM; any-asset incl. stock perps) | Vest Markets | **$0.76M** (DefiLlama) — very small | No published APR; points program (5x-style boosts per aggregators) | LPs earn risk-pricing fees paid by traders | Yes | Tiny TVL = capacity/abandonment risk; yield mostly speculative points |
| **HLP** | House-side MM/liquidation vault | Hyperliquid **native perps only** — legacy HLP does NOT market-make HIP-3/xyz builder markets (deployers bootstrap own liquidity) | $256M (DefiLlama, 2026-07-11; was $350-500M+ in 2025) | ~15-30% APR across 2026 quarterly windows, spiky (VaultVision 2026 guide); drawdowns 5-12% in trending markets | Market-making spread, funding, liquidations; 4-day lockup | Yes | No RWA-perp exposure; short-vol profile |
| **Ventuals VLP (via Hyperbeat wVLP)** | House-side LP for a HIP-3 deployer (pre-IPO company perps) | Ventuals HIP-3 dex on Hyperliquid | **$2.9M** (DefiLlama) | Not published; earns dex fees/PnL of Ventuals markets | Deposit USDT0 → wVLP; instant redeem 0.5% fee or 48h free (Hyperbeat docs) | Yes | Closest live thing to "LP the RWA-perp house" on Hyperliquid; small, opaque, new |
| **Hyperliquid user vaults on xyz** | Copy-trade vaults | HIP-3 (trade.xyz equities, XYZ100...) | n/a | n/a | 10% perf fee to leader model | Yes in principle | **Legacy user vaults cannot trade HIP-3 perps** (HL docs: vaults trade validator-operated perps only). New HyperEVM/CoreWriter vault architecture adds "full Core access incl. HIP-3" — emerging, no sizable named xyz-basis vault found on trackers (ASXN hyperscreener, Hypurrscan, PreFomo list vaults but none flagged as HIP-3 funding-harvest with material TVL) |
| **Pendle Boros funding markets** | Tradable funding-rate legs (YU); closest to "short retail crowding" instrument | Hyperliquid + Binance funding; **BTC/ETH live**; NVDA-Hyperliquid funding market reported listed (OAK Research), equity list (SPX, TSLA, AMZN) flagged as roadmap — treat equity legs as announced/unverified | ~$91M deposits, $6.9B OI cumulative by YE-2025 (OAK) | Cross-exchange funding arb strategies quoted 6.0-11.4% fixed APR (Boros Medium, 2025-2026) | Pay-fixed/receive-floating on perp funding; shorting YU = collecting crowded-long funding at a locked rate | Yes (position caps per market) | Margin product, not passive deposit; equity markets thin/new |
| **Ethena equity/commodity basis** | Synthetic-dollar basis expansion | Binance + Hyperliquid equity & commodity perps | — | — (sUSDe today: 3.9% APY, $1.57B pool — crypto basis) | **PROPOSED ONLY** — options put to risk committee per Ethena blog, covered by Bankless 2026-04-06; no approved allocation | n/a | Would be the "Ethena for equities" if approved |
| **Liminal xHYPE basis** | Delta-neutral basis vault (crypto) | Hyperliquid HYPE spot vs perp | $5.6M | 7.7% APY now / 6.3% 30d (DefiLlama) | Long spot HYPE / short perp funding capture; positions itself as future aggregator of HIP-3-era HL yields | Yes | Crypto funding, not RWA — included as nearest live architecture |
| **Falcon Finance sUSDf** | Multi-strategy synthetic dollar | CEX/DEX funding arb, stat arb; **markets tokenized-stock collateral** (mint USDf against tokenized S&P exposure) — collateral-side RWA, not RWA-funding yield | $70.9M pool | 5.1% APY (DefiLlama) | Funding arb (incl. negative-funding), staking, options | Yes | Blended/opaque strategy mix |
| **Neutrl sNUSD** | Market-neutral synthetic dollar | OTC locked-token discounts + perp hedges | — (Messari-covered, live) | varies | OTC discount capture hedged with perp shorts | Yes | Altcoin OTC risk, not RWA perps |
| **Hermetica USDh** | BTC delta-neutral dollar | BTC perp funding | small | ~BTC funding | Short BTC perps vs spot | Yes | Bitcoin-only, no equity exposure |
| **Kraken xStocks perps** | Venue (not a vault) | Kraken regulated tokenized-equity perps (xStocks framework), non-US | — | — | Enables DIY carry: long xStock spot / short xStocks perp | Non-US eligible clients | No packaged passive product yet; DIY basis only |
| **Dreamcash vaults** | App vaults on Hyperliquid (CASH equity product added Jan 2026, USDT0-paired) | Hyperliquid incl. RWA | not published | Season-1 XP + weekly USDT payouts (from 2026-02-18) | App-level vaults page exists (trade.dreamcash.xyz/vaults, JS-only, contents unverified); marketing mentions delta-neutral yield strategies | Yes | Unverified — could not read vault list; treat as announced/early |

## Notes by question

### 1. Delta-neutral RWA funding-harvest vaults
No live, at-scale product found that shorts equity/RWA perps against tokenized-stock spot and passes funding through as a deposit yield. Status of named candidates: **Ethena** — proposed to risk committee only (2026-04-06). **Neutrl/Resolv/Hermetica** — crypto-only strategies. **Falcon** — accepts tokenized-stock *collateral* and cites tokenized equities in vision posts, but sUSDf yield is crypto-strategy blend. **Liminal** — HYPE basis today, RWA/HIP-3 yields stated as roadmap thesis. Tiger Research / CoinGecko (2026) describe delta-neutral spot-vs-perp on tokenized stocks and "basis hedge funds" as an emerging *institutional/prop* activity with funding compressed to high single digits by Q2-2026 — i.e., the trade exists, the retail wrapper mostly doesn't yet.

### 2. Hyperliquid user vaults on xyz
Blocked at the protocol level for legacy vaults ("vaults can trade validator-operated perps but not spot or HIP-3 perps" — HL docs). New CoreWriter/HyperEVM vault standard advertises full Core access incl. HIP-3 in all quote assets; expect first xyz funding-harvest copy-vaults there. Trackers: ASXN hyperscreener (vaults overview), Hypurrscan stats, PreFomo vault analyzer, Loris.tools (HIP-3 dex stats). None surfaced a sizable HIP-3 basis vault as of today.

### 3. House-side LP current numbers (2026-07-11)
Ostium OLP ~4-7% APY realized with -7.4% lifetime max DD (post-redesign it is fee-only unless buffer exhausts); Avantis 8.5% (unified vault); Gains gUSDC 2-4% spot / ~7.5% 30d; Vest de-minimis ($0.76M); HLP ~15-30% APR band but crypto-native only and does not touch builder dexes.

### 4. "Short retail crowding" packaging
Pendle **Boros** is the only live instrument class: sell/short Yield Units on perp funding to receive fixed vs crowded-long floating funding. Live: BTC, ETH funding on Hyperliquid & Binance (launched on HL late 2025; cross-exchange strategies 6-11% fixed APR per Pendle). Equity-perp funding legs (NVDA-Hyperliquid, then SPX/TSLA/AMZN) reported by OAK Research as listing/roadmap — could not confirm live on-app today; treat as announced. No structured note found that shorts stock-perp funding for passive depositors.

## Sources (accessed 2026-07-11)
- https://tradingstrategy.ai/trading-view/vaults/ostium-liquidity-pool-vault (OLP TVL/APY/DD)
- https://docs.ostium.com/vault/overview and https://www.ostium.com/blog/olp-updates-a-more-seamless-vault-experience-for-liquidity-providers (OLP redesign mechanics)
- https://x.com/OstiumLabs/status/1877845429360181640 (Jan 2025, 37% 7d-SMA APR datapoint)
- https://yields.llama.fi/pools + https://api.llama.fi/tvl/{ostium,vest-markets,hyperliquid-hlp,ventuals} (same-day APY/TVL)
- https://invezz.com/news/2025/10/14/perp-dex-avantis-transitions-to-a-unified-vault-to-enhance-defi-liquidity/ (tranche merge)
- https://docs.avantisfi.com/liquidity-providers/risk-management-tranches (legacy tranche mechanics)
- https://www.bankless.com/read/news/ethena-reaches-for-yield-beyond-crypto-perps (2026-04-06, Ethena equity-basis proposal status)
- https://blog.kraken.com/product/xstocks/tokenized-equity-perpetual-futures (xStocks perps launch)
- https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/vaults + /hyperliquid-improvement-proposals-hips/hip-3-builder-deployed-perpetuals (vault HIP-3 restriction; HIP-3 mainnet 2025-10-13)
- https://vaultvision.tech/blog/hyperliquid-yield-guide (HLP 2026 APR band, drawdowns)
- https://oakresearch.io/en/analyses/innovations/boros-funding-rate-futures-on-pendle (Boros stats; NVDA/equity funding listings claim)
- https://medium.com/boros-fi/cross-exchange-funding-rate-arbitrage-a-fixed-yield-strategy-through-boros-c9e828b61215 (6-11.4% fixed APR)
- https://www.rootdata.com/news/362657 (Boros HL launch, BTC/ETH caps)
- https://docs.hyperbeat.org/hyperbeat-builder-codes/vaults/ventuals-hip-3-vlp-vault (Ventuals VLP mechanics)
- https://reports.tiger-research.com/p/2026-tokenized-stock-market-the-rise-eng (Q2-2026 funding compression, basis-fund landscape)
- https://messari.io/report/neutrl-otc-and-delta-neutral-strategies ; https://falcon.finance/news/unlocking-onchain-liquidity-and-yield-with-tokenized-stocks
- https://dreamcash.xyz/ + https://trade.dreamcash.xyz/vaults (CASH equity product Jan 2026; vaults page unverifiable via fetch)
- https://coinmetrics.substack.com/p/state-of-the-network-issue-368 (XYZ100 traction; tradeXYZ dominance)
