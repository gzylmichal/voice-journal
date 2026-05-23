"""
News collector — Google News RSS + Polish news RSS.

Returns structured dict.
"""

import feedparser

GLOBAL_FEEDS = [
    {
        "name": "Google News — World",
        "url": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
    },
    {
        "name": "Google News — Business",
        "url": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
    },
    {
        "name": "Google News — Technology",
        "url": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en",
    },
]

POLISH_FEEDS = [
    {
        "name": "Google News — Polska",
        "url": "https://news.google.com/rss/headlines?hl=pl&gl=PL&ceid=PL:pl",
    },
    {
        "name": "TVN24",
        "url": "https://tvn24.pl/najwazniejsze.xml",
    },
]


def _parse_feed(url: str, max_items: int) -> list[dict]:
    try:
        feed = feedparser.parse(url)
        articles = []
        for entry in feed.entries[:max_items]:
            title = entry.get("title", "").strip()
            if title:
                articles.append({
                    "title": title,
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                })
        return articles
    except Exception:
        return []


def _deduplicate(articles: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for a in articles:
        key = a["title"].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(a)
    return unique


def collect_news(cfg: dict) -> dict:
    """Collect global and Polish news headlines as structured data."""

    global_count = cfg.get("news_global_count", 7)
    polish_count = cfg.get("news_polish_count", 7)

    global_articles = []
    for feed_def in GLOBAL_FEEDS:
        global_articles.extend(_parse_feed(feed_def["url"], max_items=5))
    global_articles = _deduplicate(global_articles)[:global_count]

    polish_articles = []
    for feed_def in POLISH_FEEDS:
        polish_articles.extend(_parse_feed(feed_def["url"], max_items=5))
    polish_articles = _deduplicate(polish_articles)[:polish_count]

    return {
        "global": global_articles,
        "polish": polish_articles,
    }


def to_text(data: dict) -> str:
    if not data:
        return "[No news data]"
    lines = ["GLOBAL NEWS:"]
    if data.get("global"):
        for i, a in enumerate(data["global"], 1):
            lines.append(f"  {i}. {a['title']}")
    else:
        lines.append("  [No global news]")
    lines.append("")
    lines.append("POLISH NEWS:")
    if data.get("polish"):
        for i, a in enumerate(data["polish"], 1):
            lines.append(f"  {i}. {a['title']}")
    else:
        lines.append("  [No Polish news]")
    return "\n".join(lines)
