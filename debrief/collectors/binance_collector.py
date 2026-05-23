"""
Binance collector — overnight crypto price snapshot.

Returns structured dict. Public API only (no auth).
"""

import requests


BINANCE_BASE = "https://api.binance.com"
DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT"]


def collect_binance(cfg: dict) -> dict:
    """Fetch 24h price snapshots for tracked symbols."""
    symbols = cfg.get("binance_symbols", DEFAULT_SYMBOLS)

    tickers = []
    for symbol in symbols:
        try:
            data = _get_24h_ticker(symbol)
            if data:
                pair = symbol.replace("USDT", "/USDT")
                tickers.append({
                    "symbol": symbol,
                    "pair": pair,
                    "price": float(data["lastPrice"]),
                    "change_pct": float(data["priceChangePercent"]),
                    "high": float(data["highPrice"]),
                    "low": float(data["lowPrice"]),
                })
        except Exception as exc:
            tickers.append({"symbol": symbol, "error": str(exc)})

    return {"tickers": tickers}


def _get_24h_ticker(symbol: str) -> dict | None:
    url = f"{BINANCE_BASE}/api/v3/ticker/24hr"
    resp = requests.get(url, params={"symbol": symbol}, timeout=10)
    resp.raise_for_status()
    return resp.json()


def to_text(data: dict) -> str:
    if not data or not data.get("tickers"):
        return "[No crypto data]"
    lines = ["Crypto (24h):"]
    for t in data["tickers"]:
        if "error" in t:
            lines.append(f"  {t['symbol']}: [error: {t['error']}]")
        else:
            direction = "↑" if t["change_pct"] >= 0 else "↓"
            lines.append(
                f"  {t['pair']}: ${t['price']:,.2f} {direction}{abs(t['change_pct']):.1f}% "
                f"(range ${t['low']:,.2f}–${t['high']:,.2f})"
            )
    return "\n".join(lines)
