from __future__ import annotations

import re
import unicodedata

_INVISIBLE_CHARS_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u200b\u200c\u200d\u2060\ufeff]"
)
_NBSP_CHARS_RE = re.compile(r"[\u00a0\u2007\u202f\t]")
_MULTI_HORIZONTAL_SPACE_RE = re.compile(r"[ \t\f\v]+")
_MULTI_WHITESPACE_RE = re.compile(r"\s+")


def normalize_line_text(text: str, *, keep_soft_hyphen: bool = False) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFC", text)
    normalized = _INVISIBLE_CHARS_RE.sub("", normalized)
    if not keep_soft_hyphen:
        normalized = normalized.replace("\u00ad", "")
    normalized = _NBSP_CHARS_RE.sub(" ", normalized)
    normalized = _MULTI_HORIZONTAL_SPACE_RE.sub(" ", normalized)
    return normalized.strip()


def normalize_text(text: str, *, preserve_newlines: bool = False) -> str:
    if not text:
        return ""
    if preserve_newlines:
        lines = [normalize_line_text(line) for line in text.splitlines()]
        return "\n".join(line for line in lines if line)
    normalized = unicodedata.normalize("NFC", text)
    normalized = _INVISIBLE_CHARS_RE.sub("", normalized)
    normalized = normalized.replace("\u00ad", "")
    normalized = _NBSP_CHARS_RE.sub(" ", normalized)
    normalized = _MULTI_WHITESPACE_RE.sub(" ", normalized)
    return normalized.strip()
