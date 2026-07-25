"""Shared helpers for Hyperliquid info-API collectors."""
import time

import requests

INFO_URL = "https://api.hyperliquid.xyz/info"
OUT_DIR = "/Users/dereklou/Projects/equity-perp/data/raw/hyperliquid"

_session = requests.Session()

BUILDER_DEXES = ["xyz", "flx", "vntl", "hyna", "km", "abcd", "cash", "para", "mkts"]

# ---------------------------------------------------------------- asset classes
# Classification by base ticker (portion after "dex:"). Main-dex assets are all
# crypto perps. Baskets/thematic indices and ETFs are grouped under equity_index.
_PRECIOUS = {"GOLD", "SILVER", "PLATINUM", "PALLADIUM", "GOLDJM", "SILVERJM"}
_COMMODITY = {
    "BRENTOIL", "CL", "OIL", "USOIL", "WTI", "NATGAS", "GAS", "TTF", "COPPER",
    "ALUMINIUM", "CORN", "WHEAT", "SOY", "URANIUM", "DRAM", "H100",
}
_FX = {"EUR", "GBP", "JPY", "KRW", "DXY"}
_EQ_INDEX = {
    # broad indices
    "SP500", "US500", "USA500", "USA100", "XYZ100", "USTECH", "SMALL2000",
    "JP225", "JPN225", "KR200", "NIFTY", "IBOV",
    # sector/thematic indices & ETFs & baskets
    "SEMI", "SEMIS", "MAG7", "INFOTECH", "ROBOT", "NUCLEAR", "DEFENSE",
    "ENERGY", "BIOTECH", "USENERGY", "GLDMINE", "GIGADEV", "QNT", "BOT",
    "EWY", "EWJ", "EWT", "EWZ", "SMH", "XLE", "URNM", "KWEB",
}
_CRYPTO = {
    "BTC", "ETH", "SOL", "HYPE", "ZEC", "XRP", "LIGHTER", "BNB", "DOGE",
    "SUI", "PUMP", "FARTCOIN", "ENA", "XMR", "LTC", "LINK", "XPL", "BCH",
    "ADA", "1000PEPE", "BASED", "LIT", "IP", "USDE",
    # crypto-dominance indices on para
    "TOTAL2", "OTHERS", "BTCD",
}
_OTHER = {"VIX", "VOL", "USBOND", "PURRDAT", "SHAZ"}
# Everything else stock-like defaults to single_stock (incl. pre-IPO: SPCX,
# SPACEX, OPENAI, ANTHROPIC, MINIMAX, ZHIPU, CBRS=Cerebras; intl: SMSN, SKHX,
# SKHY, HYUNDAI, KIOXIA, SOFTBANK, IBIDEN, TENCENT, XIAOMI; NOK=Nokia).


def classify_asset(full_name: str) -> str:
    if ":" not in full_name:
        return "crypto"  # main dex
    dex, base = full_name.split(":", 1)
    if base in _PRECIOUS:
        return "precious_metal"
    if base in _COMMODITY:
        return "commodity"
    if base in _FX:
        return "fx"
    if base in _EQ_INDEX:
        return "equity_index"
    if base in _CRYPTO:
        return "crypto"
    if base in _OTHER:
        return "other"
    return "single_stock"


def post(body: dict, max_retries: int = 6, timeout: int = 30):
    """POST to the info endpoint with 429/5xx exponential backoff."""
    backoff = 2.0
    for attempt in range(max_retries):
        try:
            r = _session.post(INFO_URL, json=body, timeout=timeout)
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                raise
            print(f"  request error {e!r}; retrying in {backoff:.0f}s")
            time.sleep(backoff)
            backoff *= 2
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == max_retries - 1:
                r.raise_for_status()
            print(f"  HTTP {r.status_code}; backing off {backoff:.0f}s")
            time.sleep(backoff)
            backoff *= 2
            continue
        r.raise_for_status()
    raise RuntimeError("unreachable")
