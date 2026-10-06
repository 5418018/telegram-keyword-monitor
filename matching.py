"""Match explicitly configured stock names against an article title only."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    reasons: tuple[str, ...] = ()
    excluded_by: str | None = None


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split()).casefold()


def extract_title(message: object) -> str:
    """Prefer Telegram's linked article title; otherwise use the first text line.

    Never fall back to matching the entire body when a title is unavailable.
    """
    webpage = getattr(getattr(message, "media", None), "webpage", None)
    title = getattr(webpage, "title", None)
    if isinstance(title, str) and title.strip():
        return title.strip()
    text = getattr(message, "message", "") or ""
    for line in text.splitlines():
        line = line.strip()
        if line:
            if re.match(r"https?://", line, re.IGNORECASE):
                return ""
            return line
    return ""


def contains_name(title: str, name: str) -> bool:
    name = normalize(name)
    if not name:
        return False
    # Accept Korean particles, but not arbitrary company-name suffixes.
    particles = "에서는|에게는|으로는|에서|에게|으로|와의|과의|은|는|이|가|을|를|의|에|와|과|도|만|로"
    suffix = rf"(?:(?:{particles}))?" if re.search(r"[가-힣]$", name) else ""
    pattern = rf"(?<!\w){re.escape(name)}{suffix}(?!\w)"
    return re.search(pattern, normalize(title)) is not None


def match_message(
    title: str,
    *,
    keywords: Iterable[str],
    urgent_keywords: Iterable[str] = (),
    exclude_keywords: Iterable[str] = (),
    regex_patterns: Iterable[str] = (),
    match_mode: str = "any",
    stock_aliases: Mapping[str, Sequence[str]] | None = None,
) -> MatchResult:
    match_mode = match_mode.strip().lower()
    if match_mode not in ("any", "all"):
        raise ValueError("match_mode must be 'any' or 'all'")
    keywords = list(dict.fromkeys(str(word).strip() for word in keywords if str(word).strip()))
    if not title.strip() or not keywords:
        return MatchResult(False)
    for word in exclude_keywords:
        if contains_name(title, str(word)):
            return MatchResult(False, excluded_by=str(word))
    aliases = stock_aliases or {}
    hits = [
        name for name in keywords
        if any(contains_name(title, candidate) for candidate in (name, *aliases.get(name, ())))
    ]
    matched = len(hits) == len(keywords) if match_mode == "all" else bool(hits)
    if not matched:
        return MatchResult(False)
    # Urgency and custom regex can annotate a stock hit, never trigger alone.
    reasons = list(hits)
    reasons.extend(str(word) for word in urgent_keywords if contains_name(title, str(word)))
    for pattern in regex_patterns:
        pattern = str(pattern).strip()
        if pattern and re.search(pattern, title, re.IGNORECASE):
            reasons.append(f"정규식: {pattern}")
    return MatchResult(True, tuple(dict.fromkeys(reasons)))
