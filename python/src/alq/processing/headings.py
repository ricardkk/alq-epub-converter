from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
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
    r"(?:[0-9]{1,3}|[ivxlcdm]{1,12}|um|dois|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|"
    r"primeiro|segundo|terceiro|one|two|three)"
    r"(?:\s*[:\-\u2013\u2014\.]?\s*\S.*)?$",
    re.IGNORECASE,
)

_SECTION_KEYWORD_RE = re.compile(
    r"^(?:se[cç][aã]o|section)\s+"
    r"(?:[0-9]{1,3}(?:\.[0-9]{1,3})*|[ivxlcdm]{1,12})"
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

_DATE_LINE_RE = re.compile(r"^\(\s*[^()]{2,48}?\b(?:1[0-9]|20)\d{2}\s*\)\s*\*?$")
_ROMAN_NUMERAL_RE = re.compile(r"^[IVXLC]{1,6}\.?$")

_TITLE_MAX_CHARS: int = 240
_TITLE_MAX_LINES: int = 6
_MERGE_MAX_GAP_RATIO: float = 0.8
_MERGE_FONT_TOLERANCE: float = 0.6
_DISPLAY_FONT_RATIO: float = 1.3
_CENTER_TOLERANCE_RATIO: float = 0.08
_BODY_FONT_TOLERANCE: float = 0.75
_CENTERED_MIN_FONT_RATIO: float = 0.9
_CENTERED_MAX_FONT_RATIO: float = 1.22
_CENTERED_CONFIDENCE: float = 0.66
_ROMAN_CONFIDENCE: float = 0.62
_DATED_TITLE_CONFIDENCE: float = 0.92
_STRAY_LINE_MAX_CHARS: int = 60

ColumnExtent = tuple[float, float]


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


def _build_heading(
    block: ReconstructedParagraph,
    text: str,
    level: int,
    confidence: float,
) -> DetectedHeading:
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


def _is_keyword_heading(text: str) -> bool:
    return bool(_CHAPTER_KEYWORD_RE.match(text) or _STANDALONE_HEADING_KEYWORD_RE.match(text))


def _is_title_fragment_text(text: str) -> bool:
    if not text or _ROMAN_NUMERAL_RE.match(text) or _DATE_LINE_RE.match(text):
        return False
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 2:
        return False
    return all(ch.isupper() for ch in letters)


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def compute_column_extents(
    blocks: Sequence[ReconstructedCandidateBlock],
    median_font_size: float,
) -> tuple[dict[tuple[int, int], ColumnExtent], dict[int, ColumnExtent]]:
    per_page: dict[tuple[int, int], ColumnExtent] = {}
    lefts: dict[int, list[float]] = {}
    rights: dict[int, list[float]] = {}

    for block in blocks:
        if not isinstance(block, ReconstructedParagraph) or block.line_count < 3:
            continue
        if abs(block.font_size - median_font_size) > _BODY_FONT_TOLERANCE:
            continue
        key = (block.page_number, block.column_index)
        existing = per_page.get(key)
        if existing is None:
            per_page[key] = (block.bbox.x0, block.bbox.x1)
        else:
            per_page[key] = (min(existing[0], block.bbox.x0), max(existing[1], block.bbox.x1))
        lefts.setdefault(block.column_index, []).append(block.bbox.x0)
        rights.setdefault(block.column_index, []).append(block.bbox.x1)

    per_column = {column: (_median(lefts[column]), _median(rights[column])) for column in lefts}
    return per_page, per_column


def is_block_centered(
    block: ReconstructedCandidateBlock,
    per_page: dict[tuple[int, int], ColumnExtent],
    per_column: dict[int, ColumnExtent],
) -> bool:
    extent = per_page.get((block.page_number, block.column_index))
    if extent is None:
        extent = per_column.get(block.column_index)
    if extent is None:
        return False

    column_width = extent[1] - extent[0]
    if column_width <= 0.0:
        return False

    block_width = block.bbox.x1 - block.bbox.x0
    if block_width <= 0.0:
        return False

    slack = column_width * _CENTER_TOLERANCE_RATIO
    if block.bbox.x0 < extent[0] - slack or block.bbox.x1 > extent[1] + slack:
        return False

    column_center = (extent[0] + extent[1]) / 2.0
    block_center = (block.bbox.x0 + block.bbox.x1) / 2.0
    return abs(block_center - column_center) <= slack


def _can_merge_fragments(
    previous: ReconstructedParagraph,
    following: ReconstructedParagraph,
    median_font_size: float,
) -> bool:
    if previous.page_number != following.page_number:
        return False
    if previous.column_index != following.column_index:
        return False

    largest_font = max(previous.font_size, following.font_size)
    gap = following.bbox.y0 - previous.bbox.y1
    if gap > largest_font * _MERGE_MAX_GAP_RATIO or gap < -largest_font:
        return False

    if abs(previous.font_size - following.font_size) <= _MERGE_FONT_TOLERANCE:
        return True

    display_threshold = median_font_size * _DISPLAY_FONT_RATIO
    return previous.font_size >= display_threshold and following.font_size >= display_threshold


def _merge_fragment_pair(
    previous: ReconstructedParagraph,
    following: ReconstructedParagraph,
) -> ReconstructedParagraph:
    previous_text = normalize_text(previous.text)
    following_text = normalize_text(following.text)
    separator = "" if previous_text.endswith("-") else " "
    larger = previous if previous.font_size >= following.font_size else following
    return replace(
        previous,
        text=f"{previous_text}{separator}{following_text}",
        bbox=BoundingBox(
            min(previous.bbox.x0, following.bbox.x0),
            min(previous.bbox.y0, following.bbox.y0),
            max(previous.bbox.x1, following.bbox.x1),
            max(previous.bbox.y1, following.bbox.y1),
        ),
        font_size=larger.font_size,
        font_name=larger.font_name,
        is_bold=previous.is_bold or following.is_bold,
        end_page_number=following.end_page_number or following.page_number,
        line_count=previous.line_count + following.line_count,
    )


def _list_as_title_paragraph(
    block: ReconstructedList,
    per_page: dict[tuple[int, int], ColumnExtent],
    per_column: dict[int, ColumnExtent],
) -> ReconstructedParagraph | None:
    if len(block.items) != 1:
        return None
    item_text = normalize_text(block.items[0])
    if not _is_title_fragment_text(item_text) or not is_block_centered(block, per_page, per_column):
        return None
    marker = normalize_text(block.markers[0]) if block.markers else ""
    text = f"{marker} {item_text}" if marker else item_text
    line_height = block.font_size * 1.2 if block.font_size > 0.0 else 12.0
    line_count = max(1, round(block.bbox.height / line_height))
    return ReconstructedParagraph(
        text=text,
        page_number=block.page_number,
        bbox=block.bbox,
        font_size=block.font_size,
        font_name=block.font_name,
        is_bold=block.is_bold,
        is_italic=block.is_italic,
        column_index=block.column_index,
        end_page_number=block.end_page_number,
        line_count=line_count,
        flags=block.flags,
    )


def merge_title_fragments(
    blocks: Sequence[ReconstructedCandidateBlock],
    median_font_size: float,
    per_page: dict[tuple[int, int], ColumnExtent],
    per_column: dict[int, ColumnExtent],
) -> list[ReconstructedCandidateBlock]:
    merged: list[ReconstructedCandidateBlock] = []

    for original in blocks:
        block: ReconstructedCandidateBlock = original
        if isinstance(original, ReconstructedList):
            converted = _list_as_title_paragraph(original, per_page, per_column)
            if converted is not None:
                block = converted
        previous = merged[-1] if merged else None
        if (
            isinstance(previous, ReconstructedParagraph)
            and isinstance(block, ReconstructedParagraph)
            and _is_title_fragment_text(normalize_text(previous.text))
            and _is_title_fragment_text(normalize_text(block.text))
            and previous.line_count + block.line_count <= _TITLE_MAX_LINES
            and is_block_centered(previous, per_page, per_column)
            and is_block_centered(block, per_page, per_column)
            and _can_merge_fragments(previous, block, median_font_size)
        ):
            merged[-1] = _merge_fragment_pair(previous, block)
        else:
            merged.append(block)

    return merged


def _is_followed_by_date_line(blocks: Sequence[ReconstructedCandidateBlock], index: int) -> bool:
    origin = blocks[index]
    for offset in (1, 2):
        position = index + offset
        if position >= len(blocks):
            return False
        following = blocks[position]
        if following.page_number - origin.page_number > 1:
            return False
        following_text = normalize_text(following.text)
        if _DATE_LINE_RE.match(following_text):
            return True
        if not isinstance(following, ReconstructedParagraph):
            return False
        is_same_size_fragment = (
            _is_title_fragment_text(following_text)
            and len(following_text) <= _MAX_HEADING_CHARS
            and abs(following.font_size - origin.font_size) <= _MERGE_FONT_TOLERANCE
        )
        is_short_stray_line = (
            following.line_count == 1
            and len(following_text) <= _STRAY_LINE_MAX_CHARS
            and following.page_number == origin.page_number
        )
        if not (is_same_size_fragment or is_short_stray_line):
            return False
    return False


def evaluate_heading_candidate(
    block: ReconstructedCandidateBlock,
    median_font_size: float,
    *,
    followed_by_date: bool = False,
    centered: bool = False,
) -> DetectedHeading | None:
    if not isinstance(block, ReconstructedParagraph):
        return None

    text = normalize_text(block.text)
    if not text:
        return None

    if (
        followed_by_date
        and _is_title_fragment_text(text)
        and len(text) <= _TITLE_MAX_CHARS
        and block.line_count <= _TITLE_MAX_LINES
    ):
        return _build_heading(block, text, 1, _DATED_TITLE_CONFIDENCE)

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
    elif font_ratio < 0.95 and not _is_keyword_heading(text):
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

    level = pattern_level if pattern_level is not None else _infer_typographic_level(font_ratio)

    if centered and _CENTERED_MIN_FONT_RATIO <= font_ratio < _CENTERED_MAX_FONT_RATIO:
        if _ROMAN_NUMERAL_RE.match(text):
            score = max(score, _ROMAN_CONFIDENCE)
            level = 3
        elif _is_all_uppercase_title(text) and not text.endswith("."):
            score = max(score, _CENTERED_CONFIDENCE)
            level = 1 if _is_keyword_heading(text) else 2

    confidence = round(max(0.0, min(1.0, score)), 2)
    if confidence <= 0.0:
        return None

    return _build_heading(block, text, level, confidence)


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

    per_page, per_column = compute_column_extents(blocks, resolved_median)
    merged_blocks = merge_title_fragments(blocks, resolved_median, per_page, per_column)

    classified: list[ClassifiedBlock] = []
    for index, block in enumerate(merged_blocks):
        candidate = evaluate_heading_candidate(
            block,
            resolved_median,
            followed_by_date=_is_followed_by_date_line(merged_blocks, index),
            centered=is_block_centered(block, per_page, per_column),
        )
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
    "compute_column_extents",
    "compute_median_font_size",
    "detect_headings",
    "evaluate_heading_candidate",
    "is_block_centered",
    "merge_title_fragments",
]
