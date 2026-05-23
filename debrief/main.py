#!/usr/bin/env python3
"""
Morning Debrief — daily briefing email generator.

Collects structured data from multiple sources, gets a TL;DR from Gemini,
assembles an HTML email via the template, and sends it over SMTP.

Usage:
    python main.py              # Normal run: collect → synthesize → render → send
    python main.py --dry-run    # Collect + synthesize + render, write HTML to stdout
    python main.py --collect    # Only collect raw data, print text dump
    python main.py --preview    # Write rendered HTML to debrief-preview.html
"""

import sys
import argparse
import logging
from datetime import datetime, date
from pathlib import Path

from config import load_config
from collectors import weather as weather_mod
from collectors import news as news_mod
from collectors import currency as currency_mod
from collectors import calendar_collector as calendar_mod
from collectors import notion_collector as notion_mod
from collectors import binance_collector as binance_mod
from collectors import airquality_collector as aqi_mod
from collectors import history_collector as history_mod
from collectors.workout_collector import collect_today_workout
from synthesis import synthesize_tldr
from formatter import render_email
from sender import send_email

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "debrief.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("debrief")

# ---------------------------------------------------------------------------
# Collector registry: (name, collect_fn, to_text_fn)
# ---------------------------------------------------------------------------
COLLECTORS = [
    ("weather",     weather_mod.collect_weather,     weather_mod.to_text),
    ("calendar",    calendar_mod.collect_calendar,   calendar_mod.to_text),
    ("notion",      notion_mod.collect_notion,       notion_mod.to_text),
    ("news",        news_mod.collect_news,           news_mod.to_text),
    ("currency",    currency_mod.collect_currency,   currency_mod.to_text),
    ("crypto",      binance_mod.collect_binance,     binance_mod.to_text),
    ("airquality",  aqi_mod.collect_airquality,      aqi_mod.to_text),
    ("history",     history_mod.collect_history,     history_mod.to_text),
]


def run_collectors(cfg: dict) -> dict:
    """Run all collectors; return {name: data} with None for failures."""
    results = {}
    for name, fn, _ in COLLECTORS:
        logger.info("Collecting: %s", name)
        try:
            results[name] = fn(cfg)
            logger.info("  ✓ %s collected", name)
        except Exception as exc:
            logger.warning("  ✗ %s failed: %s", name, exc)
            results[name] = None
    return results


def format_text_dump(results: dict) -> str:
    """Produce a plaintext dump for --collect / synthesis input."""
    sections = []
    for name, _, to_text in COLLECTORS:
        data = results.get(name)
        header = f"=== {name.upper()} ==="
        if data is None:
            sections.append(f"{header}\n[Collection failed or not configured]")
        else:
            sections.append(f"{header}\n{to_text(data)}")
    return "\n\n".join(sections)


def main():
    parser = argparse.ArgumentParser(description="Morning Debrief generator")
    parser.add_argument("--dry-run", action="store_true",
                        help="Render HTML to stdout, don't send")
    parser.add_argument("--collect", action="store_true",
                        help="Only collect raw data, print text dump")
    parser.add_argument("--preview", action="store_true",
                        help="Write rendered HTML to debrief-preview.html")
    args = parser.parse_args()

    logger.info("=== Morning Debrief — %s ===",
                datetime.now().strftime("%Y-%m-%d %H:%M"))

    cfg = load_config()
    if args.dry_run:
        cfg["dry_run"] = True

    # Phase 1: Collect
    logger.info("Collecting: workout (today)")
    try:
        today_workout = collect_today_workout(cfg)
        logger.info("  ✓ workout collected (%d entries)", len(today_workout.get("entries", [])))
    except Exception as exc:
        logger.warning("  ✗ workout failed: %s", exc)
        today_workout = None

    results = run_collectors(cfg)
    successful = sum(1 for v in results.values() if v is not None)
    total = len(results)
    logger.info("Collection complete: %d/%d sources succeeded", successful, total)

    if args.collect:
        print(format_text_dump(results))
        return

    if successful == 0:
        logger.error("All collectors failed — aborting.")
        sys.exit(1)

    # Phase 2: Synthesize TL;DR
    today_str = datetime.now().strftime("%A, %B %d, %Y")
    logger.info("Synthesizing TL;DR with Gemini...")
    text_dump = format_text_dump(results)
    tldr = synthesize_tldr(cfg, text_dump, today_str)
    if tldr:
        logger.info("TL;DR generated (%d chars)", len(tldr))
    else:
        logger.warning("TL;DR generation returned empty — email will skip that section")

    # Phase 3: Render HTML
    html_body = render_email(
        date_str=today_str,
        location=cfg.get("location_name", ""),
        tldr=tldr,
        weather=results.get("weather"),
        calendar=results.get("calendar"),
        notion=results.get("notion"),
        currency=results.get("currency"),
        crypto=results.get("crypto"),
        news=results.get("news"),
        generated_at=datetime.now().strftime("%H:%M"),
        from_addr=cfg.get("email_from", ""),
        workout=today_workout,
        airquality=results.get("airquality"),
        history=results.get("history"),
    )

    if args.preview:
        preview_path = Path(__file__).parent / "debrief-preview.html"
        preview_path.write_text(html_body, encoding="utf-8")
        logger.info("Preview written to %s", preview_path)
        return

    if args.dry_run:
        sys.stdout.write(html_body)
        return

    # Phase 4: Send
    subject = f"Debrief — {today_str}"
    logger.info("Sending HTML email: %s", subject)
    try:
        send_email(cfg, subject, html_body, content_subtype="html")
        logger.info("✓ Debrief sent successfully.")
    except Exception as exc:
        logger.error("✗ Email send failed: %s", exc)
        sys.exit(2)


if __name__ == "__main__":
    main()
