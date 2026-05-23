"""
Currency collector — National Bank of Poland (NBP) API.

Returns structured dict; no API key required.
Docs: https://api.nbp.pl/en.html
"""

import requests


def collect_currency(cfg: dict) -> dict:
    """Fetch current PLN exchange rates from NBP, return structured dict."""

    codes = [c.strip().upper() for c in cfg.get("currency_codes", ["USD", "EUR", "GBP", "CHF"])]

    table = _fetch_table()
    if table is None:
        return {"rates": [], "date": None, "gold": None, "error": "NBP table unavailable"}

    table_date = table.get("effectiveDate", "unknown")
    rates_map = {r["code"]: r for r in table.get("rates", [])}

    rates = []
    for code in codes:
        info = rates_map.get(code)
        if info:
            rates.append({
                "code": code,
                "name": info["currency"],
                "rate": round(info["mid"], 4),
            })
        else:
            rates.append({"code": code, "name": None, "rate": None})

    # Gold price (nice-to-have)
    gold = None
    try:
        gold_resp = requests.get(
            "https://api.nbp.pl/api/cenyzlota/last/1/?format=json", timeout=10
        )
        gold_resp.raise_for_status()
        gold_data = gold_resp.json()
        if gold_data:
            gold = {
                "price_pln_per_gram": round(gold_data[0]["cena"], 2),
                "date": gold_data[0]["data"],
            }
    except Exception:
        pass

    return {"rates": rates, "date": table_date, "gold": gold}


def _fetch_table() -> dict | None:
    """Fetch NBP table A; fall back to last-available if today not published."""
    try:
        resp = requests.get(
            "https://api.nbp.pl/api/exchangerates/tables/a/?format=json", timeout=10
        )
        if resp.status_code == 404:
            resp = requests.get(
                "https://api.nbp.pl/api/exchangerates/tables/a/last/1/?format=json",
                timeout=10,
            )
        resp.raise_for_status()
        data = resp.json()
        return data[0] if data else None
    except Exception:
        return None


def to_text(data: dict) -> str:
    """Plaintext rendering."""
    if not data or not data.get("rates"):
        return "[No currency data]"
    lines = [f"PLN rates (NBP, {data.get('date', 'unknown')}):"]
    for r in data["rates"]:
        if r["rate"] is not None:
            lines.append(f"  1 {r['code']} = {r['rate']:.4f} PLN ({r['name']})")
        else:
            lines.append(f"  {r['code']}: not found")
    if data.get("gold"):
        g = data["gold"]
        lines.append(f"  Gold: {g['price_pln_per_gram']:.2f} PLN/g ({g['date']})")
    return "\n".join(lines)
