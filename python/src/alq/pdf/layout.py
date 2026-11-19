from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alq.pdf.text_extractor import ExtractedBlock, ExtractedPage

_MAX_COLUMN_WIDTH_RATIO: float = 0.56
_GUTTER_TOLERANCE_RATIO: float = 0.04
_MAX_COLUMN_OVERLAP_PT: float = 12.0


def _resolve_effective_page_width(
    blocks: Sequence[ExtractedBlock],
    page_width: float,
) -> float:
    if page_width > 0.0:
        return float(page_width)
    max_x1 = max((b.bbox.x1 for b in blocks), default=0.0)
    return max_x1 if max_x1 > 0.0 else 595.0


def _is_left_column_block(
    block: ExtractedBlock,
    mid_x: float,
    max_col_width: float,
    gutter_tolerance: float,
) -> bool:
    return (
        block.bbox.width <= max_col_width
        and block.bbox.x1 <= mid_x + gutter_tolerance
        and block.bbox.center_x < mid_x
    )


def _is_right_column_block(
    block: ExtractedBlock,
    mid_x: float,
    max_col_width: float,
    gutter_tolerance: float,
) -> bool:
    return (
        block.bbox.width <= max_col_width
        and block.bbox.x0 >= mid_x - gutter_tolerance
        and block.bbox.center_x > mid_x
    )


def is_two_column_layout(
    blocks: Sequence[ExtractedBlock],
    page_width: float,
) -> bool:
    if len(blocks) < 2:
        return False

    effective_width = _resolve_effective_page_width(blocks, page_width)
    mid_x = effective_width / 2.0
    max_col_width = effective_width * _MAX_COLUMN_WIDTH_RATIO
    gutter_tolerance = effective_width * _GUTTER_TOLERANCE_RATIO

    left_blocks = [
        b for b in blocks if _is_left_column_block(b, mid_x, max_col_width, gutter_tolerance)
    ]
    right_blocks = [
        b for b in blocks if _is_right_column_block(b, mid_x, max_col_width, gutter_tolerance)
    ]

    if not left_blocks or not right_blocks:
        return False

    max_left_x1 = max(b.bbox.x1 for b in left_blocks)
    min_right_x0 = min(b.bbox.x0 for b in right_blocks)
    return (min_right_x0 - max_left_x1) >= -_MAX_COLUMN_OVERLAP_PT


def order_page_blocks(
    blocks: Sequence[ExtractedBlock],
    page_width: float,
) -> list[ExtractedBlock]:
    if not blocks:
        return []

    effective_width = _resolve_effective_page_width(blocks, page_width)
    mid_x = effective_width / 2.0
    max_col_width = effective_width * _MAX_COLUMN_WIDTH_RATIO
    gutter_tolerance = effective_width * _GUTTER_TOLERANCE_RATIO
    two_columns = is_two_column_layout(blocks, effective_width)

    assigned: list[ExtractedBlock] = []
    for block in blocks:
        if two_columns and _is_right_column_block(block, mid_x, max_col_width, gutter_tolerance):
            col_idx = 1
        else:
            col_idx = 0
        assigned.append(replace(block, column_index=col_idx))

    return sorted(
        assigned,
        key=lambda b: (
            b.column_index,
            round(b.bbox.y0, 2),
            round(b.bbox.x0, 2),
            b.extraction_order,
        ),
    )


def order_extracted_pages(pages: Sequence[ExtractedPage]) -> list[ExtractedPage]:
    return [replace(page, blocks=order_page_blocks(page.blocks, page.width)) for page in pages]
