"""pipeline/journal.py — AI-powered journal entry formatting."""

import logging
from datetime import date
from typing import List

import ai_client
from pipeline.prompts import JOURNAL_SYSTEM_PROMPT

log = logging.getLogger(__name__)


def format_journal_entry(groq_client, transcripts: List[dict], today: date) -> str:
    """Format transcripts into a journal markdown entry."""
    parts = [f"Date: {today.strftime('%A, %B %d, %Y')}\n"]
    for t in transcripts:
        parts.append(f"[{t['time']}] {t['text']}")
    user_message = "\n\n".join(parts)

    log.info(f"Formatting journal from {len(transcripts)} memo(s)")

    try:
        journal_md = ai_client.call_ai(user_message, JOURNAL_SYSTEM_PROMPT, "Journal")
        provider = ai_client.resolve_provider()
        header = (
            f"---\n"
            f"date: {today.isoformat()}\n"
            f"memos: {len(transcripts)}\n"
            f"ai_provider: {provider}\n"
            f"---\n\n"
        )
        return header + journal_md

    except Exception:
        log.error("All AI providers failed. Using raw transcripts as fallback.")
        fallback = f"## Voice Notes — {today.strftime('%B %d, %Y')}\n\n"
        for t in transcripts:
            fallback += f"**{t['time']}**\n\n{t['text']}\n\n---\n\n"
        return fallback
