from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

from alq.errors import NoExtractableTextError, TextExtractionError
from alq.pdf.layout import order_page_blocks
from alq.pdf.reader import open_pdf
from alq.protocol import emit_debug

PYMUPDF_ITALIC_FLAG: int = 2
PYMUPDF_BOLD_FLAG: int = 16

_BOLD_FONT_TOKENS: tuple[str, ...] = ("bold", "black", "heavy", "demi", "semibold")
_ITALIC_FONT_TOKENS: tuple[str, ...] = ("italic", "oblique", "slanted")


def detect_is_bold(font_name: str, flags: int) -> bool:
    lowered = font_name.lower()
    return bool(flags & PYMUPDF_BOLD_FLAG) or any(token in lowered for token in _BOLD_FONT_TOKENS)


def detect_is_italic(font_name: str, flags: int) -> bool:
    lowered = font_name.lower()
    return bool(flags & PYMUPDF_ITALIC_FLAG) or any(
        token in lowered for token in _ITALIC_FONT_TOKENS
    )


@dataclass(frozen=True, slots=True)
class BoundingBox:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return round(max(0.0, self.x1 - self.x0), 2)

    @property
    def height(self) -> float:
        return round(max(0.0, self.y1 - self.y0), 2)

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2.0

    @classmethod
    def from_sequence(cls, coords: Sequence[float | int]) -> BoundingBox:
        if len(coords) < 4:
            return cls(0.0, 0.0, 0.0, 0.0)
        return cls(
            x0=round(float(coords[0]), 2),
            y0=round(float(coords[1]), 2),
            x1=round(float(coords[2]), 2),
            y1=round(float(coords[3]), 2),
        )

    @classmethod
    def merge(cls, boxes: Sequence[BoundingBox]) -> BoundingBox:
        if not boxes:
            return cls(0.0, 0.0, 0.0, 0.0)
        return cls(
            x0=round(min(b.x0 for b in boxes), 2),
            y0=round(min(b.y0 for b in boxes), 2),
            x1=round(max(b.x1 for b in boxes), 2),
            y1=round(max(b.y1 for b in boxes), 2),
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "x0": self.x0,
            "y0": self.y0,
            "x1": self.x1,
            "y1": self.y1,
        }


@dataclass(frozen=True, slots=True)
class ExtractedSpan:
    text: str
    bbox: BoundingBox
    font_size: float
    font_name: str
    flags: int
    is_bold: bool
    is_italic: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "bbox": self.bbox.to_dict(),
            "font_size": self.font_size,
            "font_name": self.font_name,
            "flags": self.flags,
            "is_bold": self.is_bold,
            "is_italic": self.is_italic,
        }


@dataclass(frozen=True, slots=True)
class ExtractedLine:
    text: str
    bbox: BoundingBox
    spans: list[ExtractedSpan]
    font_size: float
    font_name: str
    is_bold: bool
    is_italic: bool
    flags: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "bbox": self.bbox.to_dict(),
            "spans": [s.to_dict() for s in self.spans],
            "font_size": self.font_size,
            "font_name": self.font_name,
            "flags": self.flags,
            "is_bold": self.is_bold,
            "is_italic": self.is_italic,
        }


@dataclass(frozen=True, slots=True)
class ExtractedBlock:
    page_number: int
    text: str
    bbox: BoundingBox
    lines: list[ExtractedLine]
    font_size: float
    font_name: str
    flags: int
    is_bold: bool
    is_italic: bool
    extraction_order: int
    column_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "text": self.text,
            "bbox": self.bbox.to_dict(),
            "lines": [line.to_dict() for line in self.lines],
            "font_size": self.font_size,
            "font_name": self.font_name,
            "flags": self.flags,
            "is_bold": self.is_bold,
            "is_italic": self.is_italic,
            "extraction_order": self.extraction_order,
            "column_index": self.column_index,
        }


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    page_number: int
    width: float
    height: float
    blocks: list[ExtractedBlock]

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "width": self.width,
            "height": self.height,
            "blocks": [b.to_dict() for b in self.blocks],
        }


def _select_dominant_style(
    spans: Sequence[ExtractedSpan],
) -> tuple[float, str, int, bool, bool]:
    weights: dict[tuple[float, str, int, bool, bool], int] = {}
    for span in spans:
        key = (
            span.font_size,
            span.font_name,
            span.flags,
            span.is_bold,
            span.is_italic,
        )
        weights[key] = weights.get(key, 0) + max(1, len(span.text))

    best_key = max(weights.items(), key=lambda item: item[1])[0]
    return best_key


def _extract_span(raw_span: Mapping[str, Any]) -> ExtractedSpan | None:
    raw_text = str(raw_span.get("text", ""))
    cleaned_text = raw_text.strip()
    if not cleaned_text:
        return None

    raw_bbox = raw_span.get("bbox", (0.0, 0.0, 0.0, 0.0))
    bbox = BoundingBox.from_sequence(raw_bbox)
    font_size = round(float(raw_span.get("size", 0.0) or 0.0), 2)
    font_name = str(raw_span.get("font", "") or "").strip() or "Unknown"
    flags = int(raw_span.get("flags", 0) or 0)
    is_bold = detect_is_bold(font_name, flags)
    is_italic = detect_is_italic(font_name, flags)

    return ExtractedSpan(
        text=cleaned_text,
        bbox=bbox,
        font_size=font_size,
        font_name=font_name,
        flags=flags,
        is_bold=is_bold,
        is_italic=is_italic,
    )


def _extract_line(raw_line: Mapping[str, Any]) -> ExtractedLine | None:
    raw_spans = raw_line.get("spans")
    if not isinstance(raw_spans, Sequence):
        return None

    spans: list[ExtractedSpan] = []
    for item in raw_spans:
        if isinstance(item, Mapping):
            span = _extract_span(item)
            if span is not None:
                spans.append(span)

    if not spans:
        return None

    line_text = " ".join(s.text for s in spans).strip()
    if not line_text:
        return None

    raw_bbox = raw_line.get("bbox")
    if isinstance(raw_bbox, Sequence) and len(raw_bbox) >= 4:
        bbox = BoundingBox.from_sequence(raw_bbox)
    else:
        bbox = BoundingBox.merge([s.bbox for s in spans])

    font_size, font_name, flags, is_bold, is_italic = _select_dominant_style(spans)

    return ExtractedLine(
        text=line_text,
        bbox=bbox,
        spans=spans,
        font_size=font_size,
        font_name=font_name,
        is_bold=is_bold,
        is_italic=is_italic,
        flags=flags,
    )


def _partition_lines_by_columns(
    lines: list[ExtractedLine],
    page_width: float,
) -> list[list[ExtractedLine]]:
    if len(lines) < 2 or page_width <= 0.0:
        return [lines]

    mid_x = page_width / 2.0
    gutter_tol = page_width * 0.04
    max_col_width = page_width * 0.56

    left_lines: list[ExtractedLine] = []
    right_lines: list[ExtractedLine] = []
    for line in lines:
        if (
            line.bbox.width <= max_col_width
            and line.bbox.x1 <= mid_x + gutter_tol
            and line.bbox.center_x < mid_x
        ):
            left_lines.append(line)
        elif (
            line.bbox.width <= max_col_width
            and line.bbox.x0 >= mid_x - gutter_tol
            and line.bbox.center_x > mid_x
        ):
            right_lines.append(line)
        else:
            return [lines]

    if left_lines and right_lines:
        return [left_lines, right_lines]

    return [lines]


def _build_extracted_block(
    page_number: int,
    lines: list[ExtractedLine],
    raw_bbox: Any,
    use_raw_bbox: bool,
    extraction_order: int,
) -> ExtractedBlock | None:
    block_text = "\n".join(line.text for line in lines).strip()
    if not block_text:
        return None

    if use_raw_bbox and isinstance(raw_bbox, Sequence) and len(raw_bbox) >= 4:
        bbox = BoundingBox.from_sequence(raw_bbox)
    else:
        bbox = BoundingBox.merge([line.bbox for line in lines])

    all_spans = [span for line in lines for span in line.spans]
    font_size, font_name, flags, is_bold, is_italic = _select_dominant_style(all_spans)

    return ExtractedBlock(
        page_number=page_number,
        text=block_text,
        bbox=bbox,
        lines=lines,
        font_size=font_size,
        font_name=font_name,
        flags=flags,
        is_bold=is_bold,
        is_italic=is_italic,
        extraction_order=extraction_order,
        column_index=0,
    )


def extract_page_from_dict(
    page_dict: Mapping[str, Any],
    *,
    page_number: int,
    width: float | None = None,
    height: float | None = None,
    order_layout: bool = True,
) -> ExtractedPage:
    resolved_width = round(
        float(width if width is not None else page_dict.get("width", 595.0) or 595.0),
        2,
    )
    resolved_height = round(
        float(height if height is not None else page_dict.get("height", 842.0) or 842.0),
        2,
    )

    raw_blocks = page_dict.get("blocks", [])
    blocks: list[ExtractedBlock] = []
    next_order = 0

    if isinstance(raw_blocks, Sequence):
        for raw_block in raw_blocks:
            if not isinstance(raw_block, Mapping):
                continue
            if int(raw_block.get("type", 0) or 0) != 0:
                continue

            raw_lines = raw_block.get("lines")
            if not isinstance(raw_lines, Sequence):
                continue

            extracted_lines: list[ExtractedLine] = []
            for raw_line in raw_lines:
                if isinstance(raw_line, Mapping):
                    line = _extract_line(raw_line)
                    if line is not None:
                        extracted_lines.append(line)

            if not extracted_lines:
                continue

            line_groups = _partition_lines_by_columns(extracted_lines, resolved_width)
            use_raw_bbox = len(line_groups) == 1
            for group in line_groups:
                block = _build_extracted_block(
                    page_number=page_number,
                    lines=group,
                    raw_bbox=raw_block.get("bbox"),
                    use_raw_bbox=use_raw_bbox,
                    extraction_order=next_order,
                )
                if block is not None:
                    blocks.append(block)
                    next_order += 1

    if order_layout and blocks:
        blocks = order_page_blocks(blocks, resolved_width)

    return ExtractedPage(
        page_number=page_number,
        width=resolved_width,
        height=resolved_height,
        blocks=blocks,
    )


def extract_page(
    page: pymupdf.Page,
    *,
    page_number: int,
    order_layout: bool = True,
) -> ExtractedPage:
    try:
        rect = page.rect
        width = round(float(rect.width), 2)
        height = round(float(rect.height), 2)
        raw_dict = page.get_text("dict")
    except Exception as exc:
        raise TextExtractionError(
            f"Falha ao extrair blocos de texto da página {page_number}: {exc}",
            hint="Verifique se a página do PDF não possui objetos de fonte ou stream corrompidos.",
        ) from exc

    if not isinstance(raw_dict, Mapping):
        raise TextExtractionError(
            f"Estrutura de texto inválida retornada pelo PyMuPDF na página {page_number}."
        )

    return extract_page_from_dict(
        raw_dict,
        page_number=page_number,
        width=width,
        height=height,
        order_layout=order_layout,
    )


def extract_pdf_pages(
    path: Path | str,
    *,
    order_layout: bool = True,
    debug: bool = False,
) -> list[ExtractedPage]:
    pdf_path = Path(path)
    pages: list[ExtractedPage] = []
    total_blocks = 0

    with open_pdf(pdf_path) as doc:
        page_count = int(doc.page_count)
        for page_idx in range(page_count):
            page_number = page_idx + 1
            try:
                page = doc.load_page(page_idx)
            except Exception as exc:
                raise TextExtractionError(
                    f"Falha ao carregar a página {page_number} do PDF '{pdf_path}': {exc}",
                    hint="O documento PDF pode estar truncado ou corrompido.",
                ) from exc

            extracted_page = extract_page(
                page,
                page_number=page_number,
                order_layout=order_layout,
            )
            total_blocks += len(extracted_page.blocks)
            pages.append(extracted_page)

    emit_debug(
        f"Extração de texto concluída para '{pdf_path}': "
        f"pages={len(pages)}, total_blocks={total_blocks}",
        enabled=debug,
    )

    if total_blocks == 0:
        raise NoExtractableTextError(
            f"Nenhum texto extraível foi encontrado no arquivo PDF '{pdf_path}'.",
            hint="O documento pode ser digitalizado (imagem) e exigir OCR prévio.",
        )

    return pages


def extract_text_blocks(
    path: Path | str,
    *,
    order_layout: bool = True,
    debug: bool = False,
) -> list[ExtractedBlock]:
    pages = extract_pdf_pages(path, order_layout=order_layout, debug=debug)
    return [block for page in pages for block in page.blocks]
