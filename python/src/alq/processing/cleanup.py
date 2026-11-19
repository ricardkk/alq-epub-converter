from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace

from alq.pdf.text_extractor import ExtractedBlock, ExtractedPage
from alq.processing.normalizer import normalize_line_text, normalize_text

_ISOLATED_PAGE_NUMBER_RE = re.compile(
    r"^[\-\u2013\u2014\[\(\s]*"
    r"(?:(?:p[aá]gina|p[aá]g\.?|pag\.?|page|pg\.?)\s*)?"
    r"\d+"
    r"(?:\s*(?:/|de|of)\s*\d+)?"
    r"[\-\u2013\u2014\]\)\s]*$",
    re.IGNORECASE,
)
_DIGIT_SEQ_RE = re.compile(r"\d+")
_SIGNATURE_PUNCT_RE = re.compile(r"^[\W_]+|[\W_]+$")

_DEFAULT_MARGIN_RATIO: float = 0.14
_MAX_HEADER_FOOTER_CHARS: int = 90
_MAX_HEADER_FOOTER_LINES: int = 2


def is_isolated_page_number(text: str) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
        return False
    return bool(_ISOLATED_PAGE_NUMBER_RE.match(cleaned))


def mask_digits_for_signature(text: str) -> str:
    cleaned = normalize_text(text).lower()
    masked = _DIGIT_SEQ_RE.sub("<num>", cleaned)
    masked = _SIGNATURE_PUNCT_RE.sub("", masked).strip()
    return masked


def _is_in_top_margin(block: ExtractedBlock, page_height: float, margin_ratio: float) -> bool:
    effective_height = page_height if page_height > 0.0 else 842.0
    limit = effective_height * margin_ratio
    return block.bbox.y0 <= limit or block.bbox.y1 <= limit * 1.15


def _is_in_bottom_margin(block: ExtractedBlock, page_height: float, margin_ratio: float) -> bool:
    effective_height = page_height if page_height > 0.0 else 842.0
    limit = effective_height * (1.0 - margin_ratio)
    return block.bbox.y1 >= limit or block.bbox.y0 >= effective_height * (1.0 - margin_ratio * 1.15)


def _is_header_footer_candidate(block: ExtractedBlock, max_chars: int) -> bool:
    cleaned = normalize_text(block.text)
    if not cleaned:
        return False
    return len(block.lines) <= _MAX_HEADER_FOOTER_LINES and len(cleaned) <= max_chars


def filter_headers_and_footers(
    pages: Sequence[ExtractedPage],
    *,
    margin_ratio: float = _DEFAULT_MARGIN_RATIO,
    min_repetition_pages: int = 2,
    max_chars: int = _MAX_HEADER_FOOTER_CHARS,
) -> list[ExtractedPage]:
    if not pages:
        return []

    top_signature_pages: dict[str, set[int]] = defaultdict(set)
    bottom_signature_pages: dict[str, set[int]] = defaultdict(set)

    for page in pages:
        for block in page.blocks:
            if not _is_header_footer_candidate(block, max_chars):
                continue
            signature = mask_digits_for_signature(block.text)
            if not signature:
                continue
            if _is_in_top_margin(block, page.height, margin_ratio):
                top_signature_pages[signature].add(page.page_number)
            if _is_in_bottom_margin(block, page.height, margin_ratio):
                bottom_signature_pages[signature].add(page.page_number)

    effective_min_pages = max(2, min_repetition_pages)
    recurring_top = {
        sig
        for sig, page_nums in top_signature_pages.items()
        if len(page_nums) >= effective_min_pages
    }
    recurring_bottom = {
        sig
        for sig, page_nums in bottom_signature_pages.items()
        if len(page_nums) >= effective_min_pages
    }

    cleaned_pages: list[ExtractedPage] = []
    for page in pages:
        kept_blocks: list[ExtractedBlock] = []
        for block in page.blocks:
            in_top = _is_in_top_margin(block, page.height, margin_ratio)
            in_bottom = _is_in_bottom_margin(block, page.height, margin_ratio)

            if (in_top or in_bottom) and is_isolated_page_number(block.text):
                continue

            if _is_header_footer_candidate(block, max_chars):
                signature = mask_digits_for_signature(block.text)
                if in_top and signature in recurring_top:
                    continue
                if in_bottom and signature in recurring_bottom:
                    continue

            kept_blocks.append(block)

        cleaned_pages.append(replace(page, blocks=kept_blocks))

    return cleaned_pages


__all__ = [
    "filter_headers_and_footers",
    "is_isolated_page_number",
    "mask_digits_for_signature",
    "normalize_line_text",
    "normalize_text",
]
