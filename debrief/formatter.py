"""
HTML email formatter.

Renders the morning debrief email from structured collector data.
Design constraints:
  - Inline CSS only (survives Gmail/Outlook mangling)
  - <table> layout (Outlook strips flex/grid)
  - No external assets (no images, no web fonts, no tracking)
  - Dark mode via single <style> block with @media prefers-color-scheme
  - Graceful degradation: any missing section is omitted
"""

from html import escape
from typing import Optional

# ---------------------------------------------------------------------------
# Design tokens. Light-mode values inline; dark-mode overrides in <style>.
# ---------------------------------------------------------------------------
C = {
    "bg_page": "#f5f5f4",       # outer page bg
    "bg_card": "#ffffff",        # section card bg
    "bg_stat": "#fafaf9",        # stat card bg (slightly off-white)
    "text_primary": "#1c1b1a",
    "text_secondary": "#78716c",
    "text_tertiary": "#a8a29e",
    "border": "#e7e5e4",
    "accent": "#2563eb",         # TL;DR left border
    "accent_bg": "#eff6ff",
    "success": "#15803d",
    "danger": "#b91c1c",
}

FONT = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
    "'Helvetica Neue', Arial, sans-serif"
)

# Dark-mode overrides. Gmail/Apple Mail/Outlook (newer) honor this.
DARK_MODE_STYLE = """
  @media (prefers-color-scheme: dark) {
    body, .page { background: #1c1917 !important; }
    .card { background: #292524 !important; border-color: #44403c !important; }
    .stat { background: #1f1d1b !important; border-color: #44403c !important; }
    .tldr { background: #1e293b !important; }
    .t-primary { color: #f5f5f4 !important; }
    .t-secondary { color: #a8a29e !important; }
    .t-tertiary { color: #78716c !important; }
    .row-border { border-color: #44403c !important; }
  }
  /* Reset for Outlook */
  body { margin: 0; padding: 0; -webkit-text-size-adjust: 100%; }
  table { border-collapse: collapse; }
  /* Link color (keeps headlines readable) */
  a { color: inherit; text-decoration: none; }
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _e(s) -> str:
    """Escape for HTML."""
    return escape(str(s) if s is not None else "")


def _label(text: str) -> str:
    """Small-caps section label."""
    return (
        f'<p class="t-secondary" style="font: 500 11px/1.2 {FONT}; '
        f'letter-spacing: 0.08em; text-transform: uppercase; '
        f'color: {C["text_secondary"]}; margin: 0 0 10px;">{_e(text)}</p>'
    )


def _card_open(extra_style: str = "") -> str:
    return (
        f'<div class="card" style="background: {C["bg_card"]}; '
        f'border: 1px solid {C["border"]}; border-radius: 8px; '
        f'padding: 14px 16px; {extra_style}">'
    )


def _card_close() -> str:
    return "</div>"


def _fmt_number(n: float, decimals: int = 4) -> str:
    return f"{n:.{decimals}f}"


# ---------------------------------------------------------------------------
# Section renderers — each returns empty string if no data
# ---------------------------------------------------------------------------

def render_tldr(tldr_text: str) -> str:
    if not tldr_text:
        return ""
    return (
        f'<div class="tldr" style="background: {C["accent_bg"]}; '
        f'border-left: 3px solid {C["accent"]}; '
        f'padding: 14px 16px; border-radius: 0 8px 8px 0; '
        f'margin: 0 0 20px;">'
        f'<p class="t-primary" style="margin: 0; font: 400 14px/1.55 {FONT}; '
        f'color: {C["text_primary"]};">{_e(tldr_text)}</p>'
        f'</div>'
    )


def render_weather(weather: dict) -> str:
    if not weather or not weather.get("current"):
        return ""
    cur = weather["current"]
    today = weather.get("today") or {}

    sun_str = ""
    if today.get("sunrise") and today.get("sunset"):
        sun_str = f"{today['sunrise'][:5]} → {today['sunset'][:5]}"

    # Three stat cards in a table (Outlook-safe)
    stats = [
        ("Now", f"{_fmt_number(cur['temperature'], 0)}°", _e(cur["description"])),
        (
            "Today",
            f"{_fmt_number(today.get('temp_min', 0), 0)}–"
            f"{_fmt_number(today.get('temp_max', 0), 0)}°",
            f"{_fmt_number(today.get('precip_prob', 0), 0)}% rain",
        ),
        ("Sun", sun_str.split(" → ")[0] if sun_str else "—",
         f"→ {sun_str.split(' → ')[1]}" if sun_str else ""),
    ]

    cells = []
    for label, big, sub in stats:
        cells.append(
            f'<td class="stat" style="width: 33%; background: {C["bg_stat"]}; '
            f'border: 1px solid {C["border"]}; border-radius: 8px; '
            f'padding: 12px; vertical-align: top;">'
            f'<p class="t-secondary" style="margin: 0 0 2px; '
            f'font: 400 11px/1.2 {FONT}; color: {C["text_secondary"]};">{_e(label)}</p>'
            f'<p class="t-primary" style="margin: 0; '
            f'font: 500 20px/1.2 {FONT}; color: {C["text_primary"]};">{_e(big)}</p>'
            f'<p class="t-secondary" style="margin: 2px 0 0; '
            f'font: 400 12px/1.3 {FONT}; color: {C["text_secondary"]};">{_e(sub)}</p>'
            f'</td>'
        )

    return (
        _label("Weather") +
        f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" '
        f'style="width: 100%; border-collapse: separate; border-spacing: 8px 0; '
        f'margin: 0 -8px 20px;"><tr>' + "".join(cells) + "</tr></table>"
    )


def render_agenda(calendar: dict) -> str:
    if not calendar or not calendar.get("configured"):
        return ""
    today = calendar.get("today", [])
    tomorrow = calendar.get("tomorrow_first")

    if not today and not tomorrow:
        return ""

    rows = []
    if today:
        for i, e in enumerate(today):
            is_last = (i == len(today) - 1)
            border = (
                "" if is_last
                else f"border-bottom: 1px solid {C['border']};"
            )
            time_color = (
                C["text_tertiary"] if e.get("is_past")
                else C["text_primary"]
            )
            summary_color = (
                C["text_tertiary"] if e.get("is_past")
                else C["text_primary"]
            )
            loc_suffix = (
                f' <span class="t-secondary" style="color: {C["text_secondary"]};">'
                f'@ {_e(e["location"])}</span>'
                if e.get("location") else ""
            )
            rows.append(
                f'<tr><td class="row-border" style="padding: 10px 0; {border} '
                f'font: 500 13px/1.4 {FONT}; color: {time_color}; '
                f'width: 56px; white-space: nowrap; '
                f'font-variant-numeric: tabular-nums;">{_e(e["time"])}</td>'
                f'<td class="row-border" style="padding: 10px 0 10px 14px; {border} '
                f'font: 400 13px/1.4 {FONT}; color: {summary_color};">'
                f'{_e(e["summary"])}{loc_suffix}</td></tr>'
            )
    else:
        rows.append(
            f'<tr><td colspan="2" style="padding: 10px 0; '
            f'font: 400 13px/1.4 {FONT}; color: {C["text_secondary"]}; '
            f'font-style: italic;">No events scheduled.</td></tr>'
        )

    agenda_html = (
        _label("Agenda") +
        _card_open("padding: 4px 14px;") +
        f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" '
        f'style="width: 100%;">' + "".join(rows) + "</table>" +
        _card_close()
    )

    # Tomorrow teaser
    if tomorrow:
        loc_suffix = f' @ {tomorrow["location"]}' if tomorrow.get("location") else ""
        agenda_html += (
            f'<p class="t-secondary" style="margin: 6px 2px 20px; '
            f'font: 400 12px/1.4 {FONT}; color: {C["text_secondary"]};">'
            f'Tomorrow: {_e(tomorrow["time"])} — {_e(tomorrow["summary"])}{_e(loc_suffix)}</p>'
        )
    else:
        agenda_html += '<div style="margin-bottom: 20px;"></div>'

    return agenda_html


def _strip_markdown_table(text: str) -> str:
    """Remove embedded markdown pipe-tables from a paragraph string."""
    import re
    # Only act if a separator row exists (confirms this is actually a table)
    if not re.search(r'\|\s*-{3,}\s*\|', text):
        return text
    # Find the first '|' that follows sentence-ending punctuation — that's the table start
    m = re.search(r'(?<=[.!?,\w])\s+\|', text)
    if m:
        return text[:m.start()].strip()
    # Fallback: cut at the separator row
    m2 = re.search(r'\s*\|\s*-{3,}', text)
    return text[:m2.start()].strip() if m2 else text


def render_notion(notion: dict) -> str:
    if not notion or not notion.get("configured") or not notion.get("found"):
        return ""
    blocks = notion.get("blocks", [])
    if not blocks:
        return ""

    paragraphs = [_strip_markdown_table(b["text"]) for b in blocks if b["type"] == "paragraph" and b["text"]]
    paragraphs = [p for p in paragraphs if p]
    open_todos = [b["text"] for b in blocks if b["type"] == "todo" and not b.get("checked")]
    bullets = [b["text"] for b in blocks if b["type"] == "bullet"]

    content_parts = []
    if paragraphs:
        joined = " ".join(paragraphs[:3])
        content_parts.append(
            f'<p class="t-primary" style="margin: 0 0 8px; '
            f'font: 400 13px/1.55 {FONT}; color: {C["text_primary"]};">{_e(joined)}</p>'
        )
    elif bullets:
        content_parts.append(
            f'<p class="t-primary" style="margin: 0 0 8px; '
            f'font: 400 13px/1.55 {FONT}; color: {C["text_primary"]};">'
            f'{_e(" · ".join(bullets[:3]))}</p>'
        )

    if open_todos:
        todo_line = " · ".join(open_todos[:4])
        content_parts.append(
            f'<p class="t-secondary" style="margin: 0 0 8px; '
            f'font: 400 12px/1.5 {FONT}; color: {C["text_secondary"]};">'
            f'Open: {_e(todo_line)}</p>'
        )

    if not content_parts:
        return ""

    return (
        _label("Yesterday's notes") +
        _card_open("margin-bottom: 20px;") +
        "".join(content_parts) +
        _card_close()
    )


def render_workout(workout: dict) -> str:
    from datetime import date as _date
    if not workout or not workout.get("configured") or not workout.get("entries"):
        return ""
    entries  = workout["entries"]
    session  = workout.get("session", "")
    wk_date  = workout.get("date", "")
    is_today = wk_date == _date.today().isoformat()
    prefix   = "Today's workout" if is_today else "Yesterday's workout"
    label_text = f"{prefix} — {session}" if session else prefix

    border = f"border-bottom: 1px solid {C['border']};"
    th_style = (
        f"padding: 0 8px 6px 0; font: 500 11px/1.2 {FONT}; "
        f"color: {C['text_secondary']}; letter-spacing: 0.05em; text-align: left;"
    )

    header_row = (
        f"<tr>"
        f'<th style="{th_style}">Exercise</th>'
        f'<th style="{th_style} text-align: center;">Sets×Reps</th>'
        f'<th style="{th_style}">Weight</th>'
        f'<th style="{th_style}">Top set</th>'
        f"</tr>"
    )

    rows = []
    for e in entries:
        exercise = _e(e.get("exercise") or "")
        muscle   = _e(e.get("muscle_group") or "")
        sets_v   = str(e["sets"]) if e.get("sets") is not None else "—"
        reps_v   = str(e["reps"]) if e.get("reps") is not None else "—"
        weight   = _e(e.get("weight") or "BW")
        top_kg   = e.get("top_set_kg")

        muscle_span = (
            f'<br><span style="font-size: 11px; color: {C["text_tertiary"]};">{muscle}</span>'
            if muscle else ""
        )
        top_cell = (
            f'<td style="padding: 6px 8px 6px 0; {border} font: 400 12px/1.4 {FONT}; '
            f'color: {C["success"]}; font-variant-numeric: tabular-nums;">'
            f'{_e(str(top_kg))} kg</td>'
            if top_kg else
            f'<td style="padding: 6px 0; {border} font: 400 12px/1.4 {FONT}; '
            f'color: {C["text_tertiary"]};">—</td>'
        )

        rows.append(
            f"<tr>"
            f'<td style="padding: 6px 0; {border} font: 400 13px/1.4 {FONT}; '
            f'color: {C["text_primary"]};">{exercise}{muscle_span}</td>'
            f'<td style="padding: 6px 8px; {border} font: 400 13px/1.4 {FONT}; '
            f'color: {C["text_secondary"]}; text-align: center; white-space: nowrap;">'
            f'{_e(sets_v)}×{_e(reps_v)}</td>'
            f'<td style="padding: 6px 8px 6px 0; {border} font: 400 13px/1.4 {FONT}; '
            f'color: {C["text_secondary"]}; white-space: nowrap;">{weight}</td>'
            f"{top_cell}"
            f"</tr>"
        )

    return (
        _label(label_text) +
        _card_open("padding: 10px 16px; margin-bottom: 20px;") +
        f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="width: 100%;">'
        + header_row + "".join(rows)
        + "</table>"
        + _card_close()
    )


def render_markets(currency: dict, crypto: dict) -> str:
    """Two-column row: FX left, crypto right. Either can be None."""
    has_fx = currency and currency.get("rates")
    has_crypto = crypto and crypto.get("tickers")
    if not has_fx and not has_crypto:
        return ""

    fx_cell = _render_fx_cell(currency) if has_fx else ""
    crypto_cell = _render_crypto_cell(crypto) if has_crypto else ""

    # If only one is present, make it full width
    if has_fx and has_crypto:
        return (
            f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" '
            f'style="width: 100%; border-collapse: separate; border-spacing: 8px 0; '
            f'margin: 0 -8px 20px;"><tr>'
            f'<td style="width: 50%; vertical-align: top;">{fx_cell}</td>'
            f'<td style="width: 50%; vertical-align: top;">{crypto_cell}</td>'
            f'</tr></table>'
        )
    return f'<div style="margin-bottom: 20px;">{fx_cell or crypto_cell}</div>'


def _render_fx_cell(currency: dict) -> str:
    rows = []
    for r in currency["rates"]:
        if r["rate"] is None:
            continue
        rows.append(
            f'<tr>'
            f'<td class="t-secondary" style="padding: 4px 0; '
            f'font: 400 13px/1.4 {FONT}; color: {C["text_secondary"]};">{_e(r["code"])}</td>'
            f'<td class="t-primary" style="padding: 4px 0; text-align: right; '
            f'font: 400 13px/1.4 {FONT}; color: {C["text_primary"]}; '
            f'font-variant-numeric: tabular-nums;">{_fmt_number(r["rate"], 4)}</td>'
            f'</tr>'
        )
    if currency.get("gold"):
        g = currency["gold"]
        rows.append(
            f'<tr>'
            f'<td class="t-secondary" style="padding: 4px 0; '
            f'font: 400 13px/1.4 {FONT}; color: {C["text_secondary"]};">Gold</td>'
            f'<td class="t-primary" style="padding: 4px 0; text-align: right; '
            f'font: 400 13px/1.4 {FONT}; color: {C["text_primary"]}; '
            f'font-variant-numeric: tabular-nums;">{_fmt_number(g["price_pln_per_gram"], 2)}</td>'
            f'</tr>'
        )
    return (
        _label("PLN rates") +
        _card_open("padding: 10px 14px;") +
        f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" '
        f'style="width: 100%;">' + "".join(rows) + "</table>" +
        _card_close()
    )


def _render_crypto_cell(crypto: dict) -> str:
    rows = []
    for t in crypto["tickers"]:
        if "error" in t:
            continue
        color = C["success"] if t["change_pct"] >= 0 else C["danger"]
        sign = "+" if t["change_pct"] >= 0 else "−"
        rows.append(
            f'<tr>'
            f'<td class="t-secondary" style="padding: 4px 0; '
            f'font: 400 13px/1.4 {FONT}; color: {C["text_secondary"]};">'
            f'{_e(t["pair"].split("/")[0])}</td>'
            f'<td style="padding: 4px 0; text-align: right; '
            f'font: 400 13px/1.4 {FONT}; font-variant-numeric: tabular-nums;">'
            f'<span class="t-primary" style="color: {C["text_primary"]};">'
            f'${t["price"]:,.0f}</span> '
            f'<span style="color: {color}; font-size: 11px;">'
            f'{sign}{abs(t["change_pct"]):.1f}%</span>'
            f'</td>'
            f'</tr>'
        )
    if not rows:
        return ""
    return (
        _label("Crypto 24h") +
        _card_open("padding: 10px 14px;") +
        f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" '
        f'style="width: 100%;">' + "".join(rows) + "</table>" +
        _card_close()
    )


def render_news(news: dict) -> str:
    if not news:
        return ""
    globals_ = news.get("global", [])
    polish = news.get("polish", [])
    if not globals_ and not polish:
        return ""

    def _article(a: dict) -> str:
        title = _e(a.get("title", ""))
        url = a.get("link", "")
        if url:
            return (
                f'<p style="margin: 0 0 6px; font: 400 13px/1.5 {FONT};">'
                f'<a href="{_e(url)}" style="color: {C["text_primary"]}; '
                f'text-decoration: underline; text-decoration-color: {C["border"]};">'
                f'{title}</a></p>'
            )
        return (
            f'<p class="t-primary" style="margin: 0 0 6px; '
            f'font: 400 13px/1.5 {FONT}; color: {C["text_primary"]};">{title}</p>'
        )

    parts = []
    if globals_:
        parts.append(
            f'<p class="t-secondary" style="margin: 0 0 6px; '
            f'font: 500 11px/1.2 {FONT}; color: {C["text_secondary"]}; '
            f'letter-spacing: 0.04em;">GLOBAL</p>'
        )
        for a in globals_[:5]:
            parts.append(_article(a))
    if polish:
        parts.append(
            f'<p class="t-secondary" style="margin: 10px 0 6px; '
            f'font: 500 11px/1.2 {FONT}; color: {C["text_secondary"]}; '
            f'letter-spacing: 0.04em;">POLSKA</p>'
        )
        for a in polish[:5]:
            parts.append(_article(a))

    return (
        _label("Headlines") +
        _card_open("margin-bottom: 12px;") +
        "".join(parts) +
        _card_close()
    )


def render_airquality(aqi: dict) -> str:
    if not aqi or not aqi.get("available"):
        return ""
    label = _e(aqi.get("label", ""))
    value = aqi.get("aqi", "")
    pm25  = aqi.get("pm25")
    pm10  = aqi.get("pm10")
    sub_parts = []
    if pm25 is not None:
        sub_parts.append(f"PM2.5: {pm25} µg/m³")
    if pm10 is not None:
        sub_parts.append(f"PM10: {pm10} µg/m³")
    sub = " · ".join(sub_parts)
    return (
        _label("Air quality") +
        _card_open("margin-bottom: 20px;") +
        f'<p class="t-primary" style="margin: 0 0 2px; '
        f'font: 600 15px/1.3 {FONT}; color: {C["text_primary"]};">'
        f'AQI {_e(str(value))} — {label}</p>'
        + (
            f'<p class="t-secondary" style="margin: 2px 0 0; '
            f'font: 400 12px/1.4 {FONT}; color: {C["text_secondary"]};">{_e(sub)}</p>'
            if sub else ""
        )
        + _card_close()
    )


def render_history(history: dict) -> str:
    if not history or not history.get("available") or not history.get("events"):
        return ""
    events = history["events"]
    date_label = _e(history.get("date", ""))
    rows = []
    for e in events:
        year = _e(str(e.get("year", "")))
        text = _e(e.get("text", ""))
        url  = e.get("url", "")
        border = f"border-bottom: 1px solid {C['border']};" if e != events[-1] else ""
        linked = (
            f'<a href="{_e(url)}" style="color: {C["text_primary"]}; '
            f'text-decoration: underline; text-decoration-color: {C["border"]};">{text}</a>'
            if url else text
        )
        rows.append(
            f'<tr>'
            f'<td class="row-border" style="padding: 8px 10px 8px 0; {border} '
            f'font: 400 12px/1.4 {FONT}; color: {C["text_tertiary"]}; '
            f'white-space: nowrap; vertical-align: top;">{year}</td>'
            f'<td class="row-border" style="padding: 8px 0; {border} '
            f'font: 400 13px/1.4 {FONT}; color: {C["text_primary"]};">{linked}</td>'
            f'</tr>'
        )
    return (
        _label(f"On this day — {date_label}") +
        _card_open("padding: 4px 14px; margin-bottom: 20px;") +
        f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="width: 100%;">'
        + "".join(rows) + "</table>" +
        _card_close()
    )


def render_stale_tasks(data: dict) -> str:
    if not data or not data.get("configured"):
        return ""
    tasks = data.get("tasks", [])
    if not tasks:
        return ""
    rows = []
    for t in tasks:
        title = _e(t.get("title", ""))
        age   = _e(str(t.get("age_days", "")))
        rows.append(
            f'<p class="t-primary" style="margin: 0 0 6px; '
            f'font: 400 13px/1.5 {FONT}; color: {C["text_primary"]};">'
            f'{title} '
            f'<span class="t-secondary" style="color: {C["text_secondary"]};">'
            f'— open {age} days. Still relevant?</span></p>'
        )
    return (
        _label("Aging tasks") +
        _card_open("margin-bottom: 20px;") +
        "".join(rows) +
        _card_close()
    )


def render_training_suggestion(data: dict) -> str:
    if not data or not data.get("configured"):
        return ""
    suggestion = data.get("suggestion")
    fallback   = data.get("fallback")
    if not suggestion and not fallback:
        return ""
    if suggestion:
        last = data.get("last_date", "")
        last_str = f" (last: {_e(last)})" if last else ""
        text = f"Up next by your rotation: {_e(suggestion)}{_e(last_str)}."
    else:
        parts = [f"{_e(k)} {_e(str(v))}d" for k, v in (fallback or {}).items()]
        text = "Days since each split: " + " · ".join(parts)
    return (
        _label("Training suggestion") +
        _card_open("margin-bottom: 20px;") +
        f'<p class="t-primary" style="margin: 0; '
        f'font: 400 13px/1.5 {FONT}; color: {C["text_primary"]};">{text}</p>' +
        _card_close()
    )


# ---------------------------------------------------------------------------
# Weekly Review renderer
# ---------------------------------------------------------------------------

def _epley_1rm(weight_kg: float, reps: int) -> float:
    """Epley formula: e1RM = weight × (1 + reps/30)."""
    if reps == 1:
        return weight_kg
    return round(weight_kg * (1 + reps / 30), 1)


def render_weekly_email(data: dict) -> str:
    """
    Render the Sunday Weekly Review HTML email.
    data keys: tldr, workout, notion_week, today_str, week_label, chart_html
    """
    from datetime import date, datetime as _dt
    today    = date.today()
    week_num = today.isocalendar()[1]

    week_label = data.get("week_label", f"Week {week_num}")
    today_str  = data.get("today_str", "")
    workout    = data.get("workout", {})
    entries    = workout.get("entries", []) if workout else []

    # ── 1RM estimates (Epley) ─────────────────────────────────────────────────
    KEY_LIFT_KEYWORDS = {
        "Bench Press": ["bench"],
        "Deadlift":    ["deadlift"],
        "Squat":       ["squat"],
    }
    e1rm: dict[str, float] = {}
    for entry in entries:
        name_lower = (entry.get("exercise") or "").lower()
        top_kg = entry.get("top_set_kg")
        reps   = entry.get("reps")
        if not top_kg or not reps:
            continue
        for lift, keywords in KEY_LIFT_KEYWORDS.items():
            if any(kw in name_lower for kw in keywords):
                val = _epley_1rm(float(top_kg), int(reps))
                if val > e1rm.get(lift, 0):
                    e1rm[lift] = val
                break

    e1rm_cells = ""
    for lift in ("Bench Press", "Deadlift", "Squat"):
        val = e1rm.get(lift)
        e1rm_cells += (
            f'<td style="width:33%;padding:12px 8px;text-align:center;vertical-align:top;">'
            f'<p style="margin:0 0 4px;font:500 11px/1.2 {FONT};color:{C["text_secondary"]};'
            f'letter-spacing:0.08em;text-transform:uppercase;">{_e(lift)}</p>'
            f'<p style="margin:0;font:600 22px/1.2 {FONT};color:{C["text_primary"]};">'
            f'{_e(str(val)) + " kg" if val else "—"}</p>'
            f'</td>'
        )

    e1rm_section = ""
    if e1rm:
        e1rm_section = (
            _label("Estimated 1RM (Epley)") +
            _card_open("padding: 4px 0; margin-bottom: 20px;") +
            f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="width:100%;">'
            f'<tr>{e1rm_cells}</tr></table>' +
            _card_close()
        )

    # ── Key lifts top sets this week ──────────────────────────────────────────
    key_tops  = workout.get("key_lift_tops", {}) if workout else {}
    lift_rows = ""
    for lift, dates_map in key_tops.items():
        if dates_map:
            top_kg = dates_map[max(dates_map.keys())]
            lift_rows += (
                f'<tr>'
                f'<td style="padding:6px 0;font:400 13px/1.4 {FONT};color:{C["text_primary"]};'
                f'border-bottom:1px solid {C["border"]};">{_e(lift)}</td>'
                f'<td style="padding:6px 0;font:600 13px/1.4 {FONT};color:{C["success"]};'
                f'text-align:right;border-bottom:1px solid {C["border"]};">{top_kg} kg</td>'
                f'</tr>'
            )
        else:
            lift_rows += (
                f'<tr>'
                f'<td style="padding:6px 0;font:400 13px/1.4 {FONT};color:{C["text_tertiary"]};'
                f'border-bottom:1px solid {C["border"]};">{_e(lift)}</td>'
                f'<td style="padding:6px 0;font:400 13px/1.4 {FONT};color:{C["text_tertiary"]};'
                f'text-align:right;border-bottom:1px solid {C["border"]};">—</td>'
                f'</tr>'
            )

    session_count = workout.get("sessions", 0) if workout else 0
    session_dates = workout.get("session_dates", []) if workout else []
    chart_html    = data.get("chart_html", "")
    plural        = "s" if session_count != 1 else ""

    session_rows = ""
    for d in session_dates:
        session_type = (workout.get("session_types") or {}).get(d, "")
        try:
            day_label = _dt.fromisoformat(d).strftime("%a %b %d")
        except Exception:
            day_label = d
        session_rows += (
            f'<tr>'
            f'<td style="padding:4px 0;font:400 13px/1.4 {FONT};color:{C["text_secondary"]};">'
            f'{_e(day_label)} — {_e(session_type)}</td>'
            f'</tr>'
        )

    training_section = ""
    if entries:
        training_section = (
            _label(f"This week's training — {session_count} session{plural}") +
            _card_open("padding: 10px 16px; margin-bottom: 20px;") +
            (
                f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="width:100%;margin-bottom:12px;">'
                + lift_rows + "</table>"
                if lift_rows else ""
            ) +
            (f'<div style="margin:12px 0;">{chart_html}</div>' if chart_html else "") +
            (
                f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="width:100%;margin-top:8px;">'
                + session_rows + "</table>"
                if session_rows else ""
            ) +
            _card_close()
        )

    # ── Week in Notes ─────────────────────────────────────────────────────────
    notion_week  = data.get("notion_week", {})
    week_entries = notion_week.get("entries", []) if notion_week else []
    notes_parts  = []
    for i, e in enumerate(week_entries):
        title    = _e(e.get("title", ""))
        summary  = _e(e.get("summary", ""))
        date_str = e.get("date", "")
        try:
            day_label = _dt.fromisoformat(date_str).strftime("%a %b %d") if date_str else ""
        except Exception:
            day_label = date_str
        border = f"border-bottom:1px solid {C['border']};" if i < len(week_entries) - 1 else ""
        notes_parts.append(
            f'<div style="padding:10px 0;{border}">'
            f'<p style="margin:0 0 2px;font:400 11px/1.2 {FONT};color:{C["text_tertiary"]};'
            f'letter-spacing:0.04em;">{_e(day_label)}</p>'
            f'<p style="margin:0 0 {"4px" if summary else "0"};font:500 13px/1.4 {FONT};'
            f'color:{C["text_primary"]};">{title}</p>'
            + (f'<p style="margin:0;font:400 12px/1.5 {FONT};color:{C["text_secondary"]};">{summary}</p>'
               if summary else "")
            + "</div>"
        )

    notes_section = (
        _label("Week in notes") +
        _card_open("padding: 4px 16px; margin-bottom: 20px;") +
        "".join(notes_parts) +
        _card_close()
    ) if notes_parts else ""

    # ── TL;DR ─────────────────────────────────────────────────────────────────
    tldr = (data.get("tldr") or "").strip()
    tldr_section = render_tldr(tldr)

    # ── Assemble ──────────────────────────────────────────────────────────────
    header = (
        f'<div style="padding-bottom:14px;border-bottom:1px solid {C["border"]};'
        f'margin-bottom:20px;" class="row-border">'
        f'<p class="t-secondary" style="margin:0 0 4px;font:500 11px/1.2 {FONT};'
        f'letter-spacing:0.08em;text-transform:uppercase;color:{C["text_secondary"]};">Weekly Review</p>'
        f'<p class="t-primary" style="margin:0;font:500 18px/1.3 {FONT};color:{C["text_primary"]};">'
        f'{_e(week_label)} · {_e(today_str)}</p>'
        f'</div>'
    )

    sections_html = "".join(s for s in [
        tldr_section, e1rm_section, training_section, notes_section,
    ] if s)

    footer = (
        f'<p class="t-tertiary" style="margin:20px 0 0;text-align:center;'
        f'font:400 11px/1.4 {FONT};color:{C["text_tertiary"]};">'
        f'Generated {_e(today_str)} · weekly review</p>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>Weekly Review</title>
<style>{DARK_MODE_STYLE}</style>
</head>
<body class="page" style="background:{C["bg_page"]};margin:0;padding:0;font-family:{FONT};color:{C["text_primary"]};">
<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="width:100%;background:{C["bg_page"]};">
<tr><td align="center" style="padding:20px 12px;">
<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="width:100%;max-width:600px;">
<tr><td style="padding:0;">
{header}
{sections_html}
{footer}
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main assembler
# ---------------------------------------------------------------------------

def render_email(
    date_str: str,
    location: str,
    tldr: str,
    weather: Optional[dict],
    calendar: Optional[dict],
    notion: Optional[dict],
    currency: Optional[dict],
    crypto: Optional[dict],
    news: Optional[dict],
    generated_at: str,
    from_addr: str,
    workout: Optional[dict] = None,
    airquality: Optional[dict] = None,
    history: Optional[dict] = None,
    stale_tasks: Optional[dict] = None,
    training_suggestion: Optional[dict] = None,
) -> str:
    """Compose the full HTML email."""

    sections = [
        render_tldr(tldr),
        render_weather(weather),
        render_agenda(calendar),
        render_workout(workout),
        render_training_suggestion(training_suggestion),
        render_stale_tasks(stale_tasks),
        render_notion(notion),
        render_markets(currency, crypto),
        render_news(news),
        render_airquality(airquality),
        render_history(history),
    ]
    sections_html = "".join(s for s in sections if s)

    # If nothing rendered, show a minimal fallback
    if not sections_html:
        sections_html = (
            f'<p class="t-secondary" style="font: 400 13px/1.5 {FONT}; '
            f'color: {C["text_secondary"]};">No data collected this morning.</p>'
        )

    footer = (
        f'<p class="t-tertiary" style="margin: 20px 0 0; text-align: center; '
        f'font: 400 11px/1.4 {FONT}; color: {C["text_tertiary"]};">'
        f'Generated {_e(generated_at)} · {_e(from_addr)}</p>'
    )

    header = (
        f'<div style="padding-bottom: 14px; border-bottom: 1px solid {C["border"]}; '
        f'margin-bottom: 20px;" class="row-border">'
        f'<p class="t-secondary" style="margin: 0 0 4px; '
        f'font: 500 11px/1.2 {FONT}; letter-spacing: 0.08em; '
        f'text-transform: uppercase; color: {C["text_secondary"]};">Morning debrief</p>'
        f'<p class="t-primary" style="margin: 0; font: 500 18px/1.3 {FONT}; '
        f'color: {C["text_primary"]};">{_e(date_str)} · {_e(location)}</p>'
        f'</div>'
    )

    # Preheader text — first ~90 chars shown in inbox preview.
    # Hidden via display:none + visibility:hidden but still read by preview.
    preheader_text = (tldr or f"Morning debrief for {date_str}")[:100]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>Morning debrief</title>
<style>{DARK_MODE_STYLE}</style>
</head>
<body class="page" style="background: {C["bg_page"]}; margin: 0; padding: 0; \
font-family: {FONT}; color: {C["text_primary"]};">
<div style="display: none; max-height: 0; overflow: hidden; \
visibility: hidden; color: transparent;">{_e(preheader_text)}</div>
<table role="presentation" cellspacing="0" cellpadding="0" border="0" \
style="width: 100%; background: {C["bg_page"]};">
<tr><td align="center" style="padding: 20px 12px;">
<table role="presentation" cellspacing="0" cellpadding="0" border="0" \
style="width: 100%; max-width: 600px;">
<tr><td style="padding: 0;">
{header}
{sections_html}
{footer}
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""
