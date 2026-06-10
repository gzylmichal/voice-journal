#!/usr/bin/env python3
"""ai_client.py — Single AI provider dispatch for the Voice Journal pipeline.

Supports Claude (Anthropic), Gemini (Google), and Groq (Llama) with a
configurable provider chain. Transient errors (429/500/503) on any provider are
retried up to 3 times with 10 s back-off. If the primary provider fails,
Groq is used as a fallback (when a GROQ_API_KEY is available).

Usage:
    from ai_client import call_ai

    text = call_ai(user_message, system_prompt, label="Journal")
"""

import json
import logging
import time
from typing import Callable

try:
    import requests
except ImportError:
    raise ImportError("Missing dependency: pip install requests --break-system-packages")

from pipeline.config import (
    AI_PROVIDER,
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    GEMINI_MODEL,
    GOOGLE_API_KEY,
    GROQ_API_KEY,
    LLAMA_MODEL,
)

log = logging.getLogger(__name__)

_TRANSIENT     = {429, 500, 503}
_MAX_RETRIES   = 3
_RETRY_DELAY_S = 10


class _Transient(RuntimeError):
    """Raised by provider implementations to signal a retryable HTTP status."""


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------

def _with_retries(label: str, fn: Callable[[], str]) -> str:
    """Call fn up to _MAX_RETRIES times; retry on _Transient or network errors."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn()
        except _Transient as exc:
            if attempt < _MAX_RETRIES:
                log.warning(
                    f"{label}: {exc} (attempt {attempt}/{_MAX_RETRIES})"
                    f" — retrying in {_RETRY_DELAY_S}s"
                )
                time.sleep(_RETRY_DELAY_S)
            else:
                raise RuntimeError(f"{label}: {exc}") from exc
        except RuntimeError:
            raise
        except Exception as exc:
            if attempt < _MAX_RETRIES:
                log.warning(
                    f"{label}: network error (attempt {attempt}/{_MAX_RETRIES}): {exc}"
                    f" — retrying in {_RETRY_DELAY_S}s"
                )
                time.sleep(_RETRY_DELAY_S)
            else:
                raise RuntimeError(f"{label}: {exc}") from exc
    raise RuntimeError(f"{label}: all retries exhausted")


# ---------------------------------------------------------------------------
# Provider implementations (single attempt each)
# ---------------------------------------------------------------------------

def _call_claude(
    user_message: str,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
) -> str:
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": CLAUDE_MODEL,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
            "temperature": temperature,
        },
        timeout=60,
    )
    if resp.status_code in _TRANSIENT:
        raise _Transient(f"Claude API {resp.status_code}")
    if resp.status_code != 200:
        raise RuntimeError(f"Claude API {resp.status_code}: {resp.text[:500]}")
    return "\n".join(
        block["text"]
        for block in resp.json().get("content", [])
        if block.get("type") == "text"
    ).strip()


def _call_gemini(
    user_message: str,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GOOGLE_API_KEY}"
    )
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    resp = requests.post(
        url,
        headers={"content-type": "application/json"},
        json=payload,
        timeout=60,
    )
    if resp.status_code in _TRANSIENT:
        raise _Transient(f"Gemini API {resp.status_code}")
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini API {resp.status_code}: {resp.text[:500]}")
    candidates = resp.json().get("candidates", [])
    if not candidates:
        raise RuntimeError(
            f"Gemini returned no candidates: {json.dumps(resp.json())[:500]}"
        )
    parts = candidates[0].get("content", {}).get("parts", [])
    return "\n".join(p.get("text", "") for p in parts).strip()


def _call_groq(
    user_message: str,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
) -> str:
    try:
        from groq import Groq
    except ImportError:
        raise RuntimeError("Groq not installed: pip install groq --break-system-packages")
    try:
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model=LLAMA_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        code = getattr(exc, "status_code", None)
        if code in _TRANSIENT:
            raise _Transient(f"Groq API {code}") from exc
        raise


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------

def resolve_provider() -> str:
    """Return the active provider name: 'claude', 'gemini', or 'groq'."""
    if AI_PROVIDER != "auto":
        choice = AI_PROVIDER.lower()
        if choice == "claude" and not ANTHROPIC_API_KEY:
            log.warning("AI_PROVIDER=claude but ANTHROPIC_API_KEY not set — falling back")
        elif choice == "gemini" and not GOOGLE_API_KEY:
            log.warning("AI_PROVIDER=gemini but GOOGLE_API_KEY not set — falling back")
        elif choice in ("claude", "gemini", "groq"):
            return choice
    if ANTHROPIC_API_KEY:
        return "claude"
    if GOOGLE_API_KEY:
        return "gemini"
    return "groq"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def call_ai(
    user_message: str,
    system_prompt: str,
    label: str = "AI",
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> str:
    """Call the configured AI provider, falling back through all available providers.

    Raises RuntimeError if every provider in the chain fails.
    """
    primary = resolve_provider()
    seen: set = {primary}
    chain = [primary]
    for p, key in [("claude", ANTHROPIC_API_KEY), ("gemini", GOOGLE_API_KEY), ("groq", GROQ_API_KEY)]:
        if p not in seen and key:
            chain.append(p)
            seen.add(p)

    for provider in chain:
        try:
            log.info(f"{label}: calling {provider.upper()}...")
            if provider == "claude":
                fn = lambda: _call_claude(user_message, system_prompt, max_tokens, temperature)  # noqa: E731
            elif provider == "gemini":
                fn = lambda: _call_gemini(user_message, system_prompt, max_tokens, temperature)  # noqa: E731
            else:
                fn = lambda: _call_groq(user_message, system_prompt, max_tokens, temperature)  # noqa: E731
            return _with_retries(f"{label}/{provider.upper()}", fn)
        except Exception as exc:
            log.error(f"{label}: {provider.upper()} failed: {exc}")
            if provider != chain[-1]:
                log.info(f"{label}: falling back to next provider...")

    raise RuntimeError(f"{label}: all AI providers failed")
