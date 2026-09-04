"""Deterministic text gate: free, instant checks that run before any model scoring.

Extracted from MultiAgentCommunication ``claude_coord/wlg/pipeline/t3.py`` at
d99002a1903a56b5601d7ec3455e5dfa43028935 (the committed revision; an uncommitted upstream
working-tree edit to ``CODE_INDICATORS_HARD`` was not used). Sanitization rejects null bytes,
injection and script patterns, code and template syntax, prompt-template leaks, over-long
text and mostly non-Latin text, and normalizes quotes; ``t3_check`` enforces a ``FormatSpec``.
The pattern lists are kept verbatim so known answers match upstream; they are module
constants a host may extend in its own registry, not product vocabulary AEOS depends on.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from aeos_kernel.rubric import FormatSpec


@dataclass(frozen=True, slots=True)
class T3Result:
    passed: bool
    errors: tuple[str, ...] = field(default_factory=tuple)


DANGEROUS_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"MATCH\s*\(\w+:", "Cypher injection"),
    (r"MERGE\s*\(\w+:", "Cypher injection"),
    (r"DETACH\s+DELETE", "Cypher injection"),
    (r"CREATE\s*\(\w+:", "Cypher injection"),
    (r"SET\s+\w+\.\w+\s*=", "Cypher injection"),
    (r"DROP\s+TABLE", "SQL injection"),
    (r"ALTER\s+TABLE", "SQL injection"),
    (r"INSERT\s+INTO", "SQL injection"),
    (r"<script", "XSS"),
    (r"javascript:", "XSS"),
)

# Always-reject indicators: template syntax and code blocks.
CODE_INDICATORS_HARD: tuple[str, ...] = ("{%", "%}", "{{", "}}", "```", "console.log")

# The model copied an instruction instead of following it.
PROMPT_LEAK_PATTERNS: tuple[str, ...] = (
    r"coord wlg",
    r"<shape_id>",
    r"<SHAPE_ID>",
    r"\{WRITE:",
    r"a \d+-\d+ sentence description",
    r"one-line summary.*max \d+ chars",
)

# Code indicators that only reject when two or more co-occur.
CODE_INDICATORS_SOFT: tuple[str, ...] = (
    "SELECT ",
    "FROM ",
    "WHERE ",
    "def ",
    "class ",
    "function(",
)

MAX_TEXT_CHARS = 2000
MIN_LATIN_RATIO = 0.7
_LATIN_PUNCTUATION = "\u2013\u2014\u2018\u2019\u201c\u201d\u2026"


def _looks_like_parseable_json(text: str) -> bool:
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{" or stripped[-1] not in "]}":
        return False
    try:
        json.loads(stripped)
    except ValueError:
        return False
    return True


def sanitize(text: object) -> tuple[str | None, str | None]:
    """Sanitize model output. Returns ``(cleaned_text, error)``; ``error`` set means rejected."""
    if not isinstance(text, str):
        return None, "not a string"

    if "\x00" in text:
        return None, "contains null bytes"

    # Strip control characters, keeping newlines and tabs.
    cleaned = "".join(c for c in text if c in ("\n", "\t") or (ord(c) >= 32 and ord(c) != 127))

    # A JSON-structured value keeps its ASCII quotes so a consumer can parse it back;
    # everything else gets shell-safe quote normalization, exactly as upstream.
    preserve_quotes = _looks_like_parseable_json(cleaned)
    if preserve_quotes:
        cleaned = (
            cleaned.replace("\u201c", '"')
            .replace("\u201d", '"')
            .replace("\u2018", "'")
            .replace("\u2019", "'")
        )
    else:
        # ' → U+2019, " → U+201D, ` → U+2018 (shell-safe equivalents, as upstream)
        cleaned = cleaned.replace("'", "\u2019").replace('"', "\u201d").replace("`", "\u2018")

    for pattern, label in DANGEROUS_PATTERNS:
        if re.search(pattern, cleaned, re.IGNORECASE):
            return None, f"dangerous: {label}"

    for indicator in CODE_INDICATORS_HARD:
        if indicator in cleaned:
            return None, f"code detected: '{indicator}'"

    soft_hits = [ind for ind in CODE_INDICATORS_SOFT if ind in cleaned]
    if len(soft_hits) >= 2:
        return None, f"code detected: {soft_hits}"

    for pattern in PROMPT_LEAK_PATTERNS:
        if re.search(pattern, cleaned, re.IGNORECASE):
            return None, f"prompt leak: '{pattern}'"

    if len(cleaned) > MAX_TEXT_CHARS:
        return None, f"too long ({len(cleaned)} chars)"

    latin_count = sum(1 for c in cleaned if ord(c) < 0x250 or c in _LATIN_PUNCTUATION)
    latin_ratio = latin_count / max(len(cleaned), 1)
    if latin_ratio < MIN_LATIN_RATIO:
        return None, f"too much non-Latin ({latin_ratio:.0%})"

    return cleaned.strip(), None


def _matches_format(text: str, fmt: str) -> bool:
    upper = text.upper()
    if fmt == "GIVEN/WHEN/THEN":
        return "GIVEN" in upper and "WHEN" in upper and "THEN" in upper
    return True  # unknown formats pass by default


def t3_check(output: Any, format_spec: FormatSpec) -> T3Result:
    """Run every deterministic check against ``output`` (a string or a list of strings)."""
    errors: list[str] = []

    if isinstance(output, str):
        items: list[Any] = [output]
    elif isinstance(output, list):
        items = output
    else:
        return T3Result(passed=False, errors=(f"unexpected type: {type(output).__name__}",))

    sanitized_items: list[Any] = []
    for i, item in enumerate(items):
        if isinstance(item, str):
            clean, err = sanitize(item)
            if err:
                errors.append(f"item[{i}] sanitize: {err}")
            else:
                sanitized_items.append(clean)
        else:
            sanitized_items.append(item)

    if errors:
        return T3Result(passed=False, errors=tuple(errors))

    if format_spec.min_items is not None and len(sanitized_items) < format_spec.min_items:
        errors.append(f"item_count={len(sanitized_items)} < min={format_spec.min_items}")
    if format_spec.max_items is not None and len(sanitized_items) > format_spec.max_items:
        errors.append(f"item_count={len(sanitized_items)} > max={format_spec.max_items}")

    for i, item in enumerate(sanitized_items):
        if not isinstance(item, str):
            continue
        min_chars = format_spec.min_chars_per_item
        max_chars = format_spec.max_chars_per_item
        if min_chars is not None and len(item) < min_chars:
            errors.append(f"item[{i}] length={len(item)} < min={min_chars}")
        if max_chars is not None and len(item) > max_chars:
            errors.append(f"item[{i}] length={len(item)} > max={max_chars}")
        for phrase in format_spec.banned_phrases:
            if phrase.lower() in item.lower():
                errors.append(f"item[{i}] banned phrase: '{phrase}'")
        if format_spec.required_format and not _matches_format(item, format_spec.required_format):
            errors.append(f"item[{i}] missing format: {format_spec.required_format}")

    if format_spec.min_sentences is not None or format_spec.max_sentences is not None:
        full_text = " ".join(str(x) for x in sanitized_items)
        sentence_count = len([s for s in re.split(r"[.!?]", full_text) if s.strip()])
        if format_spec.min_sentences is not None and sentence_count < format_spec.min_sentences:
            errors.append(f"sentences={sentence_count} < min={format_spec.min_sentences}")
        if format_spec.max_sentences is not None and sentence_count > format_spec.max_sentences:
            errors.append(f"sentences={sentence_count} > max={format_spec.max_sentences}")

    return T3Result(passed=not errors, errors=tuple(errors))
