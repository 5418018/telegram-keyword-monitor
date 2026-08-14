"""Pure, testable message matching helpers."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(value.split())


def _normalized_terms(values: Iterable[str]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for value in values:
        original = str(value).strip()
        normalized = normalize(original)
        if normalized:
            result.append((original, normalized))
    return result


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    reasons: tuple[str, ...] = ()
    excluded_by: str | None = None


def match_message(
    text: str,
    *,
    keywords: Iterable[str],
    urgent_keywords: Iterable[str],
    exclude_keywords: Iterable[str],
    regex_patterns: Iterable[str] = (),
    match_mode: str = "any",
) -> MatchResult:
    """Return whether text matches the configured rules.

    Exclusions win. Urgent terms always match. Normal keywords use either
    ``any`` or ``all`` mode. Regex matches are treated like urgent matches.
    """

    normalized_text = normalize(text)
    if not normalized_text:
        return MatchResult(False)

    for original, term in _normalized_terms(exclude_keywords):
        if term in normalized_text:
            return MatchResult(False, excluded_by=original)

    reasons: list[str] = []
    for original, term in _normalized_terms(urgent_keywords):
        if term in normalized_text:
            reasons.append(original)

    for pattern in regex_patterns:
        pattern = str(pattern).strip()
        if pattern and re.search(pattern, text, flags=re.IGNORECASE):
            reasons.append(f"정규식: {pattern}")

    if reasons:
        return MatchResult(True, tuple(dict.fromkeys(reasons)))

    normal_terms = _normalized_terms(keywords)
    hits = [original for original, term in normal_terms if term in normalized_text]
    mode = match_mode.strip().lower()
    if mode == "all":
        matched = bool(normal_terms) and len(hits) == len(normal_terms)
    elif mode == "any":
        matched = bool(hits)
    else:
        raise ValueError("match_mode must be 'any' or 'all'")

    return MatchResult(matched, tuple(hits) if matched else ())

