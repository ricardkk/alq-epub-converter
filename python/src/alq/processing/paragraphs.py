from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from alq.pdf.text_extractor import BoundingBox, ExtractedBlock, ExtractedLine, ExtractedPage
from alq.processing.cleanup import filter_headers_and_footers
from alq.processing.normalizer import normalize_line_text, normalize_text

_UNORDERED_LIST_RE = re.compile(r"^([•●○▪▫\*]|[\-\u2013\u2014])\s+(.+)$")
_ORDERED_LIST_RE = re.compile(
    r"^(\(?\d{1,3}[\.\)]|\(?[a-zA-Z][\.\)]|\(?[ivxlcdmIVXLCDM]{1,4}[\.\)])\s+(.+)$"
)
_TERMINAL_SENTENCE_CHARS: tuple[str, ...] = (".", "!", "?", ":", ";")
_TRAILING_CLOSERS: str = "\"'”’»)]}"


@dataclass(frozen=True, slots=True)
class ListItemMatch:
    ordered: bool
    marker: str
    text: str


@dataclass(frozen=True, slots=True)
class ReconstructedParagraph:
    text: str
    page_number: int
    bbox: BoundingBox
    font_size: float
    font_name: str
    is_bold: bool
    is_italic: bool
    column_index: int = 0
    end_page_number: int | None = None
    line_count: int = 1
    flags: int = 0

    @property
    def kind(self) -> Literal["paragraph"]:
        return "paragraph"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "text": self.text,
            "page_number": self.page_number,
            "end_page_number": self.end_page_number or self.page_number,
            "bbox": self.bbox.to_dict(),
            "font_size": self.font_size,
            "font_name": self.font_name,
            "is_bold": self.is_bold,
            "is_italic": self.is_italic,
            "column_index": self.column_index,
            "line_count": self.line_count,
            "flags": self.flags,
        }


@dataclass(frozen=True, slots=True)
class ReconstructedList:
    ordered: bool
    items: list[str]
    page_number: int
    bbox: BoundingBox
    font_size: float
    font_name: str
    is_bold: bool
    is_italic: bool
    column_index: int = 0
    end_page_number: int | None = None
    flags: int = 0
    markers: list[str] = field(default_factory=list)

    @property
    def kind(self) -> Literal["list"]:
        return "list"

    @property
    def text(self) -> str:
        return "\n".join(self.items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ordered": self.ordered,
            "items": list(self.items),
            "markers": list(self.markers),
            "page_number": self.page_number,
            "end_page_number": self.end_page_number or self.page_number,
            "bbox": self.bbox.to_dict(),
            "font_size": self.font_size,
            "font_name": self.font_name,
            "is_bold": self.is_bold,
            "is_italic": self.is_italic,
            "column_index": self.column_index,
            "flags": self.flags,
        }


ReconstructedCandidateBlock = ReconstructedParagraph | ReconstructedList


def _first_letter_or_digit(text: str) -> str | None:
    stripped = text.lstrip()
    for ch in stripped:
        if ch.isalnum():
            return ch
    return None


def _starts_with_lowercase(text: str) -> bool:
    ch = _first_letter_or_digit(text)
    return ch is not None and ch.isalpha() and ch.islower()


def _starts_with_uppercase(text: str) -> bool:
    ch = _first_letter_or_digit(text)
    return ch is not None and ch.isalpha() and ch.isupper()


def _ends_with_terminal_punctuation(text: str) -> bool:
    stripped = text.rstrip().rstrip(_TRAILING_CLOSERS).rstrip()
    if not stripped:
        return False
    return stripped.endswith(_TERMINAL_SENTENCE_CHARS)


def _join_two_line_segments(prev_text: str, next_text: str) -> str:
    prev_clean = normalize_line_text(prev_text, keep_soft_hyphen=True)
    next_clean = normalize_line_text(next_text, keep_soft_hyphen=True)

    if not prev_clean:
        return next_clean.replace("\u00ad", "")
    if not next_clean:
        return prev_clean.replace("\u00ad", "")

    if prev_clean.endswith("\u00ad") and len(prev_clean) >= 2 and prev_clean[-2].isalpha():
        stem = prev_clean[:-1].replace("\u00ad", "")
        continuation = next_clean.replace("\u00ad", "")
        if _starts_with_lowercase(continuation):
            return f"{stem}{continuation}"
        return f"{stem}-{continuation}"

    if prev_clean.endswith("-") and len(prev_clean) >= 2 and prev_clean[-2].isalpha():
        stem = prev_clean[:-1].replace("\u00ad", "")
        continuation = next_clean.replace("\u00ad", "")
        first_ch = _first_letter_or_digit(continuation)
        if first_ch is not None and first_ch.isalpha() and first_ch.islower():
            return f"{stem}{continuation}"
        if first_ch is not None and (first_ch.isupper() or first_ch.isdigit()):
            return f"{stem}-{continuation}"

    return f"{prev_clean.replace('\u00ad', '')} {next_clean.replace('\u00ad', '')}"


def join_hyphenated_lines(
    first: Sequence[str] | str,
    second: str | None = None,
) -> str:
    if isinstance(first, str):
        if second is not None:
            segments = [first, second]
        else:
            segments = first.splitlines()
    else:
        segments = list(first)

    cleaned_segments = [
        normalize_line_text(seg, keep_soft_hyphen=True)
        for seg in segments
        if normalize_line_text(seg, keep_soft_hyphen=True)
    ]
    if not cleaned_segments:
        return ""

    acc = cleaned_segments[0]
    for seg in cleaned_segments[1:]:
        acc = _join_two_line_segments(acc, seg)

    return normalize_text(acc.replace("\u00ad", ""))


def parse_list_item(text: str) -> ListItemMatch | None:
    cleaned = normalize_line_text(text)
    if not cleaned:
        return None

    unordered_match = _UNORDERED_LIST_RE.match(cleaned)
    if unordered_match is not None:
        marker = unordered_match.group(1).strip()
        item_text = normalize_text(unordered_match.group(2))
        if item_text:
            return ListItemMatch(ordered=False, marker=marker, text=item_text)

    ordered_match = _ORDERED_LIST_RE.match(cleaned)
    if ordered_match is not None:
        marker = ordered_match.group(1).strip()
        item_text = normalize_text(ordered_match.group(2))
        if item_text:
            return ListItemMatch(ordered=True, marker=marker, text=item_text)

    return None


@dataclass(slots=True)
class _AnnotatedLine:
    line: ExtractedLine
    page_number: int
    column_index: int
    flags: int


@dataclass(slots=True)
class _ParagraphAccumulator:
    page_number: int
    column_index: int
    font_size: float
    font_name: str
    is_bold: bool
    is_italic: bool
    flags: int
    lines: list[str]
    bboxes: list[BoundingBox]
    last_line: ExtractedLine
    min_x0: float
    max_width: float

    def to_paragraph(self) -> ReconstructedParagraph:
        return ReconstructedParagraph(
            text=join_hyphenated_lines(self.lines),
            page_number=self.page_number,
            bbox=BoundingBox.merge(self.bboxes),
            font_size=self.font_size,
            font_name=self.font_name,
            is_bold=self.is_bold,
            is_italic=self.is_italic,
            column_index=self.column_index,
            end_page_number=self.page_number,
            line_count=len(self.lines),
            flags=self.flags,
        )


@dataclass(slots=True)
class _ListAccumulator:
    ordered: bool
    page_number: int
    column_index: int
    font_size: float
    font_name: str
    is_bold: bool
    is_italic: bool
    flags: int
    items: list[str]
    markers: list[str]
    bboxes: list[BoundingBox]
    last_line: ExtractedLine
    marker_x0: float

    def to_list(self) -> ReconstructedList:
        return ReconstructedList(
            ordered=self.ordered,
            items=[normalize_text(item) for item in self.items if normalize_text(item)],
            markers=list(self.markers),
            page_number=self.page_number,
            bbox=BoundingBox.merge(self.bboxes),
            font_size=self.font_size,
            font_name=self.font_name,
            is_bold=self.is_bold,
            is_italic=self.is_italic,
            column_index=self.column_index,
            end_page_number=self.page_number,
            flags=self.flags,
        )


def _extract_annotated_lines_from_block(block: ExtractedBlock) -> list[_AnnotatedLine]:
    if block.lines:
        return [
            _AnnotatedLine(
                line=line,
                page_number=block.page_number,
                column_index=block.column_index,
                flags=line.flags or block.flags,
            )
            for line in block.lines
            if normalize_line_text(line.text, keep_soft_hyphen=True)
        ]

    raw_text_lines = [
        seg for seg in block.text.splitlines() if normalize_line_text(seg, keep_soft_hyphen=True)
    ]
    if not raw_text_lines:
        return []

    line_count = len(raw_text_lines)
    step_h = block.bbox.height / max(1, line_count)
    annotated: list[_AnnotatedLine] = []
    for idx, seg in enumerate(raw_text_lines):
        y0 = round(block.bbox.y0 + idx * step_h, 2)
        y1 = round(y0 + max(step_h, block.font_size), 2)
        synthetic_line = ExtractedLine(
            text=seg,
            bbox=BoundingBox(block.bbox.x0, y0, block.bbox.x1, y1),
            spans=[],
            font_size=block.font_size,
            font_name=block.font_name,
            is_bold=block.is_bold,
            is_italic=block.is_italic,
            flags=block.flags,
        )
        annotated.append(
            _AnnotatedLine(
                line=synthetic_line,
                page_number=block.page_number,
                column_index=block.column_index,
                flags=block.flags,
            )
        )
    return annotated


def _should_split_paragraph(
    acc: _ParagraphAccumulator,
    candidate: _AnnotatedLine,
    column_left_margin: float,
) -> bool:
    if candidate.column_index != acc.column_index:
        return True

    curr_line = candidate.line
    last_line = acc.last_line

    if abs(curr_line.font_size - acc.font_size) > 1.5:
        return True

    if curr_line.is_bold != acc.is_bold:
        return True

    last_height = max(last_line.bbox.height, last_line.font_size, 10.0)
    vertical_gap = curr_line.bbox.y0 - last_line.bbox.y1
    y0_step = curr_line.bbox.y0 - last_line.bbox.y0

    if y0_step < -2.0:
        return True

    if vertical_gap > max(last_height * 0.6, last_line.font_size * 0.85):
        return True

    if y0_step > last_line.font_size * 2.05:
        return True

    indent_threshold = max(10.0, curr_line.font_size * 0.9)
    ref_left_x0 = min(acc.min_x0, column_left_margin)

    if (curr_line.bbox.x0 - last_line.bbox.x0) >= indent_threshold:
        return True

    if (curr_line.bbox.x0 - ref_left_x0) >= indent_threshold and _ends_with_terminal_punctuation(
        acc.lines[-1]
    ):
        return True

    if (
        len(acc.lines) >= 2
        and _ends_with_terminal_punctuation(acc.lines[-1])
        and last_line.bbox.width < acc.max_width * 0.72
        and _starts_with_uppercase(curr_line.text)
    ):
        return True

    return False


def _can_continue_list_item(
    acc: _ListAccumulator,
    candidate: _AnnotatedLine,
) -> bool:
    if candidate.column_index != acc.column_index:
        return False

    curr_line = candidate.line
    last_line = acc.last_line

    if abs(curr_line.font_size - acc.font_size) > 1.5:
        return False

    if curr_line.is_bold != acc.is_bold:
        return False

    last_height = max(last_line.bbox.height, last_line.font_size, 10.0)
    vertical_gap = curr_line.bbox.y0 - last_line.bbox.y1
    y0_step = curr_line.bbox.y0 - last_line.bbox.y0

    if y0_step < -2.0 or vertical_gap > max(last_height * 0.55, last_line.font_size * 0.75):
        return False

    if y0_step > last_line.font_size * 1.95:
        return False

    if curr_line.bbox.x0 < acc.marker_x0 - 2.0:
        return False

    is_indented_continuation = curr_line.bbox.x0 >= acc.marker_x0 + 6.0
    prev_unfinished = not _ends_with_terminal_punctuation(acc.items[-1])
    return is_indented_continuation or prev_unfinished


def _can_append_next_list_item(
    acc: _ListAccumulator,
    candidate: _AnnotatedLine,
    match: ListItemMatch,
) -> bool:
    if acc.ordered != match.ordered:
        return False
    if candidate.column_index != acc.column_index:
        return False

    curr_line = candidate.line
    last_line = acc.last_line

    if abs(curr_line.font_size - acc.font_size) > 1.5:
        return False

    last_height = max(last_line.bbox.height, last_line.font_size, 10.0)
    vertical_gap = curr_line.bbox.y0 - last_line.bbox.y1
    y0_step = curr_line.bbox.y0 - last_line.bbox.y0

    if y0_step < -2.0:
        return False

    return vertical_gap <= max(last_height * 1.35, last_line.font_size * 1.8)


def reconstruct_page_blocks(page: ExtractedPage) -> list[ReconstructedCandidateBlock]:
    annotated_lines: list[_AnnotatedLine] = []
    for block in page.blocks:
        annotated_lines.extend(_extract_annotated_lines_from_block(block))

    if not annotated_lines:
        return []

    col_min_x0: dict[int, float] = {}
    for item in annotated_lines:
        col = item.column_index
        x0 = item.line.bbox.x0
        col_min_x0[col] = min(col_min_x0[col], x0) if col in col_min_x0 else x0

    results: list[ReconstructedCandidateBlock] = []
    para_acc: _ParagraphAccumulator | None = None
    list_acc: _ListAccumulator | None = None

    def flush() -> None:
        nonlocal para_acc, list_acc
        if para_acc is not None:
            para = para_acc.to_paragraph()
            if para.text:
                results.append(para)
            para_acc = None
        if list_acc is not None:
            lst = list_acc.to_list()
            if lst.items:
                results.append(lst)
            list_acc = None

    for item in annotated_lines:
        raw_line_text = normalize_line_text(item.line.text, keep_soft_hyphen=True)
        if not raw_line_text:
            continue

        list_match = parse_list_item(raw_line_text)
        if list_match is not None:
            if para_acc is not None:
                flush()
            if list_acc is not None and _can_append_next_list_item(list_acc, item, list_match):
                list_acc.items.append(list_match.text)
                list_acc.markers.append(list_match.marker)
                list_acc.bboxes.append(item.line.bbox)
                list_acc.last_line = item.line
            else:
                flush()
                list_acc = _ListAccumulator(
                    ordered=list_match.ordered,
                    page_number=item.page_number,
                    column_index=item.column_index,
                    font_size=item.line.font_size,
                    font_name=item.line.font_name,
                    is_bold=item.line.is_bold,
                    is_italic=item.line.is_italic,
                    flags=item.flags,
                    items=[list_match.text],
                    markers=[list_match.marker],
                    bboxes=[item.line.bbox],
                    last_line=item.line,
                    marker_x0=item.line.bbox.x0,
                )
            continue

        if list_acc is not None:
            if _can_continue_list_item(list_acc, item):
                list_acc.items[-1] = _join_two_line_segments(list_acc.items[-1], raw_line_text)
                list_acc.bboxes.append(item.line.bbox)
                list_acc.last_line = item.line
                continue
            flush()

        col_margin = col_min_x0.get(item.column_index, item.line.bbox.x0)
        if para_acc is not None and not _should_split_paragraph(para_acc, item, col_margin):
            para_acc.lines.append(raw_line_text)
            para_acc.bboxes.append(item.line.bbox)
            para_acc.last_line = item.line
            para_acc.min_x0 = min(para_acc.min_x0, item.line.bbox.x0)
            para_acc.max_width = max(para_acc.max_width, item.line.bbox.width)
        else:
            flush()
            para_acc = _ParagraphAccumulator(
                page_number=item.page_number,
                column_index=item.column_index,
                font_size=item.line.font_size,
                font_name=item.line.font_name,
                is_bold=item.line.is_bold,
                is_italic=item.line.is_italic,
                flags=item.flags,
                lines=[raw_line_text],
                bboxes=[item.line.bbox],
                last_line=item.line,
                min_x0=item.line.bbox.x0,
                max_width=item.line.bbox.width,
            )

    flush()
    return results


def _can_merge_paragraphs_across_page_break(
    prev_block: ReconstructedCandidateBlock,
    next_block: ReconstructedCandidateBlock,
) -> bool:
    if not isinstance(prev_block, ReconstructedParagraph):
        return False
    if not isinstance(next_block, ReconstructedParagraph):
        return False

    if _ends_with_terminal_punctuation(prev_block.text):
        return False

    if not _starts_with_lowercase(next_block.text):
        return False

    if abs(prev_block.font_size - next_block.font_size) > 1.5:
        return False

    if prev_block.is_bold != next_block.is_bold or prev_block.is_italic != next_block.is_italic:
        return False

    return True


def reconstruct_blocks_from_pages(
    pages: Sequence[ExtractedPage],
    *,
    clean_headers_footers: bool = True,
    merge_across_pages: bool = True,
) -> list[ReconstructedCandidateBlock]:
    if not pages:
        return []

    working_pages = filter_headers_and_footers(pages) if clean_headers_footers else list(pages)

    combined: list[ReconstructedCandidateBlock] = []
    for page in working_pages:
        page_blocks = reconstruct_page_blocks(page)
        if not page_blocks:
            continue

        if (
            merge_across_pages
            and combined
            and _can_merge_paragraphs_across_page_break(combined[-1], page_blocks[0])
        ):
            prev_para = combined[-1]
            next_para = page_blocks[0]
            assert isinstance(prev_para, ReconstructedParagraph)
            assert isinstance(next_para, ReconstructedParagraph)

            merged_text = join_hyphenated_lines(prev_para.text, next_para.text)
            combined[-1] = ReconstructedParagraph(
                text=merged_text,
                page_number=prev_para.page_number,
                bbox=prev_para.bbox,
                font_size=prev_para.font_size,
                font_name=prev_para.font_name,
                is_bold=prev_para.is_bold,
                is_italic=prev_para.is_italic,
                column_index=prev_para.column_index,
                end_page_number=next_para.end_page_number or next_para.page_number,
                line_count=prev_para.line_count + next_para.line_count,
                flags=prev_para.flags,
            )
            combined.extend(page_blocks[1:])
        else:
            combined.extend(page_blocks)

    return combined


def reconstruct_paragraphs(
    pages: Sequence[ExtractedPage],
    *,
    clean_headers_footers: bool = True,
    merge_across_pages: bool = True,
) -> list[ReconstructedCandidateBlock]:
    return reconstruct_blocks_from_pages(
        pages,
        clean_headers_footers=clean_headers_footers,
        merge_across_pages=merge_across_pages,
    )


__all__ = [
    "ListItemMatch",
    "ReconstructedCandidateBlock",
    "ReconstructedList",
    "ReconstructedParagraph",
    "join_hyphenated_lines",
    "parse_list_item",
    "reconstruct_blocks_from_pages",
    "reconstruct_page_blocks",
    "reconstruct_paragraphs",
]
