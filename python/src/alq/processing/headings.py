from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from alq.pdf.text_extractor import BoundingBox
from alq.processing.normalizer import normalize_text
from alq.processing.paragraphs import (
    ReconstructedCandidateBlock,
    ReconstructedList,
    ReconstructedParagraph,
)

DEFAULT_MIN_HEADING_CONFIDENCE: float = 0.60
_MAX_HEADING_CHARS: int = 120
_MAX_HEADING_WORDS: int = 18
_MAX_HEADING_LINES: int = 3

_CHAPTER_KEYWORD_RE = re.compile(
    r"^(?:cap[ií]tulo|chapter|parte|part|livro|book)\s+"
    r"(?:[0-9]{1,3}|[ivxlcdm]{1,7}|um|dois|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|"
    r"primeiro|segundo|terceiro|one|two|three)"
    r"(?:\s*[:\-\u2013\u2014\.]?\s*\S.*)?$",
    re.IGNORECASE,
)

_SECTION_KEYWORD_RE = re.compile(
    r"^(?:se[cç][aã]o|section)\s+"
    r"(?:[0-9]{1,3}(?:\.[0-9]{1,3})*|[ivxlcdm]{1,7})"
    r"(?:\s*[:\-\u2013\u2014\.]?\s*\S.*)?$",
    re.IGNORECASE,
)

_STANDALONE_HEADING_KEYWORD_RE = re.compile(
    r"^(?:pr[oó]logo|prologue|ep[ií]logo|epilogue|pref[aá]cio|preface|"
    r"introdu[cç][aã]o|introduction|conclus[aã]o|conclusion|ap[eê]ndice|appendix|"
    r"posf[aá]cio|agradecimentos|refer[eê]ncias|bibliografia|sum[aá]rio)"
    r"(?:\s*[:\-\u2013\u2014]\s+\S.*)?$",
    re.IGNORECASE,
)

_HIERARCHICAL_LEVEL3_RE = re.compile(
    r"^[1-9]\d?\.\d{1,2}\.\d{1,2}(?:\.\d{1,2})*\.?\s+[A-ZÀ-ÖØ-Þ]\S*.*$"
)

_HIERARCHICAL_LEVEL2_RE = re.compile(r"^[1-9]\d?\.\d{1,2}\.?\s+[A-ZÀ-ÖØ-Þ]\S*.*$")

_HIERARCHICAL_LEVEL1_RE = re.compile(
    r"^(?:[1-9]\d?|[IVX]{1,5})(?:[\.\-\u2013\u2014])?\s+[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ]+.*$"
)


@dataclass(frozen=True, slots=True)
class DetectedHeading:
    text: str
    level: int
    confidence: float
    page_number: int
    font_size: float
    is_bold: bool
    bbox: BoundingBox = field(default_factory=lambda: BoundingBox(0.0, 0.0, 0.0, 0.0))
    font_name: str = "Helvetica"
    is_italic: bool = False
    column_index: int = 0

    @property
    def kind(self) -> Literal["heading"]:
        return "heading"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "text": self.text,
            "level": self.level,
            "confidence": self.confidence,
            "page_number": self.page_number,
            "font_size": self.font_size,
            "is_bold": self.is_bold,
            "bbox": self.bbox.to_dict(),
            "font_name": self.font_name,
            "is_italic": self.is_italic,
            "column_index": self.column_index,
        }


HeadingCandidate = DetectedHeading
ClassifiedBlock = DetectedHeading | ReconstructedParagraph | ReconstructedList


def _weighted_median(pairs: Sequence[tuple[float, int]]) -> float:
    if not pairs:
        return 11.0
    sorted_pairs = sorted(pairs, key=lambda item: item[0])
    total_weight = sum(weight for _, weight in sorted_pairs)
    if total_weight <= 0:
        return round(float(sorted_pairs[int(len(sorted_pairs) / 2)][0]), 2)

    half = total_weight / 2.0
    cumulative = 0
    for size, weight in sorted_pairs:
        cumulative += weight
        if cumulative >= half:
            return round(float(size), 2)
    return round(float(sorted_pairs[-1][0]), 2)


def compute_median_font_size(blocks: Sequence[ReconstructedCandidateBlock]) -> float:
    if not blocks:
        return 11.0

    body_pairs: list[tuple[float, int]] = []
    all_pairs: list[tuple[float, int]] = []

    for block in blocks:
        if block.font_size <= 0.0:
            continue
        text = normalize_text(block.text)
        weight = max(1, len(text))
        all_pairs.append((block.font_size, weight))

        if isinstance(block, ReconstructedList):
            body_pairs.append((block.font_size, weight))
        elif len(text) >= 60 or text.endswith(".") or not block.is_bold:
            body_pairs.append((block.font_size, weight))

    if body_pairs:
        return _weighted_median(body_pairs)
    return _weighted_median(all_pairs)


def _match_textual_heading_pattern(text: str) -> tuple[int, float] | None:
    if _CHAPTER_KEYWORD_RE.match(text):
        return (1, 0.55)
    if _STANDALONE_HEADING_KEYWORD_RE.match(text):
        return (1, 0.52)
    if _SECTION_KEYWORD_RE.match(text):
        return (2, 0.50)
    if _HIERARCHICAL_LEVEL3_RE.match(text):
        return (3, 0.50)
    if _HIERARCHICAL_LEVEL2_RE.match(text):
        return (2, 0.50)
    if _HIERARCHICAL_LEVEL1_RE.match(text):
        return (1, 0.46)
    return None


def _is_all_uppercase_title(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 3:
        return False
    return all(ch.isupper() for ch in letters)


def _infer_typographic_level(font_ratio: float) -> int:
    if font_ratio >= 1.45:
        return 1
    if font_ratio >= 1.22:
        return 2
    return 3


def evaluate_heading_candidate(
    block: ReconstructedCandidateBlock,
    median_font_size: float,
) -> DetectedHeading | None:
    if not isinstance(block, ReconstructedParagraph):
        return None

    text = normalize_text(block.text)
    if not text:
        return None

    if len(text) > _MAX_HEADING_CHARS or block.line_count > _MAX_HEADING_LINES:
        return None

    words = text.split()
    word_count = len(words)
    if word_count == 0 or word_count > _MAX_HEADING_WORDS:
        return None

    if text.endswith((",", ";")):
        return None

    first_alpha = next((ch for ch in text if ch.isalpha()), None)
    if first_alpha is None or first_alpha.islower():
        return None

    safe_median = median_font_size if median_font_size > 0.0 else 11.0
    font_ratio = block.font_size / safe_median
    pattern_match = _match_textual_heading_pattern(text)

    if text.endswith("."):
        if font_ratio < 1.25:
            return None
        if word_count > 7 and pattern_match is None:
            return None

    score = 0.0
    pattern_level: int | None = None

    if pattern_match is not None:
        pattern_level, pattern_bonus = pattern_match
        score += pattern_bonus

    if font_ratio >= 1.55:
        score += 0.58
    elif font_ratio >= 1.35:
        score += 0.52
    elif font_ratio >= 1.22:
        score += 0.46
    elif font_ratio >= 1.12:
        score += 0.30
    elif font_ratio < 0.95:
        score -= 0.25

    if block.is_bold:
        score += 0.18

    if word_count <= 8 and len(text) <= 65:
        score += 0.15
    elif word_count <= 12 and len(text) <= 90:
        score += 0.08

    if _is_all_uppercase_title(text) and (font_ratio >= 1.10 or block.is_bold or pattern_match):
        score += 0.12

    if text.endswith("."):
        score -= 0.25

    if pattern_match is None and font_ratio < 1.12:
        score = min(score, 0.45)

    confidence = round(max(0.0, min(1.0, score)), 2)
    if confidence <= 0.0:
        return None

    level = pattern_level if pattern_level is not None else _infer_typographic_level(font_ratio)

    return DetectedHeading(
        text=text,
        level=level,
        confidence=confidence,
        page_number=block.page_number,
        font_size=block.font_size,
        is_bold=block.is_bold,
        bbox=block.bbox,
        font_name=block.font_name,
        is_italic=block.is_italic,
        column_index=block.column_index,
    )


def classify_headings(
    blocks: Sequence[ReconstructedCandidateBlock],
    *,
    median_font_size: float | None = None,
    min_confidence: float = DEFAULT_MIN_HEADING_CONFIDENCE,
) -> list[ClassifiedBlock]:
    if not blocks:
        return []

    resolved_median = (
        median_font_size if median_font_size is not None else compute_median_font_size(blocks)
    )

    classified: list[ClassifiedBlock] = []
    for block in blocks:
        candidate = evaluate_heading_candidate(block, resolved_median)
        if candidate is not None and candidate.confidence >= min_confidence:
            classified.append(candidate)
        else:
            classified.append(block)

    return classified


def detect_headings(
    blocks: Sequence[ReconstructedCandidateBlock],
    *,
    median_font_size: float | None = None,
    min_confidence: float = DEFAULT_MIN_HEADING_CONFIDENCE,
) -> list[DetectedHeading]:
    classified = classify_headings(
        blocks,
        median_font_size=median_font_size,
        min_confidence=min_confidence,
    )
    return [item for item in classified if isinstance(item, DetectedHeading)]


__all__ = [
    "ClassifiedBlock",
    "DEFAULT_MIN_HEADING_CONFIDENCE",
    "DetectedHeading",
    "HeadingCandidate",
    "classify_headings",
    "compute_median_font_size",
    "detect_headings",
    "evaluate_heading_candidate",
]
