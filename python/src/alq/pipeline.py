from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alq.domain.blocks import Block, Heading, ImageBlock, ListBlock, Paragraph
from alq.domain.document import Chapter, Document, ImageAsset
from alq.domain.metadata import Metadata
from alq.pdf.image_extractor import (
    ExtractedImagePlacement,
    ImageExtractionResult,
    extract_pdf_images,
)
from alq.pdf.ocr import OcrMode
from alq.pdf.reader import PdfInspectionResult, inspect_pdf
from alq.pdf.text_extractor import ExtractedPage, extract_pdf_pages_with_ocr
from alq.processing.cleanup import filter_headers_and_footers
from alq.processing.headings import (
    DEFAULT_MIN_HEADING_CONFIDENCE,
    ClassifiedBlock,
    DetectedHeading,
    classify_headings,
)
from alq.processing.paragraphs import (
    ReconstructedCandidateBlock,
    ReconstructedList,
    ReconstructedParagraph,
    reconstruct_blocks_from_pages,
)

ENV_ALQ_DEBUG_DIR: str = "ALQ_DEBUG_DIR"
_SAFE_STEM_RE = re.compile(r"[^A-Za-z0-9._-]+")

FlowItem = ClassifiedBlock | ExtractedImagePlacement


@dataclass(frozen=True, slots=True)
class PipelineArtifacts:
    inspection: PdfInspectionResult
    extracted_pages: list[ExtractedPage]
    cleaned_pages: list[ExtractedPage]
    reconstructed_blocks: list[ReconstructedCandidateBlock]
    classified_blocks: list[ClassifiedBlock]
    document: Document
    image_extraction: ImageExtractionResult = field(default_factory=ImageExtractionResult)

    def to_dict(self) -> dict[str, Any]:
        return {
            "extracted_pages": [page.to_dict() for page in self.extracted_pages],
            "cleaned_pages": [page.to_dict() for page in self.cleaned_pages],
            "reconstructed_blocks": [block.to_dict() for block in self.reconstructed_blocks],
            "classified_blocks": [block.to_dict() for block in self.classified_blocks],
            "image_extraction": self.image_extraction.to_dict(),
            "document": self.document.to_dict(),
        }


def _to_domain_block(item: FlowItem) -> Block:
    if isinstance(item, DetectedHeading):
        return Heading(text=item.text, level=item.level)
    if isinstance(item, ReconstructedList):
        return ListBlock(ordered=item.ordered, items=list(item.items))
    if isinstance(item, ReconstructedParagraph):
        return Paragraph(text=item.text)
    if isinstance(item, ExtractedImagePlacement):
        return ImageBlock(asset_id=item.asset_id, alt_text=item.alt_text)
    raise TypeError(f"Unsupported block type: {type(item)!r}")


def interleave_blocks_and_images(
    classified_blocks: Sequence[ClassifiedBlock],
    image_placements: Sequence[ExtractedImagePlacement],
) -> list[FlowItem]:
    if not image_placements:
        return list(classified_blocks)
    if not classified_blocks:
        return list(image_placements)

    combined: list[tuple[int, int, float, float, int, FlowItem]] = []
    idx = 0
    for block in classified_blocks:
        combined.append(
            (
                block.page_number,
                block.column_index,
                round(block.bbox.y0, 2),
                round(block.bbox.x0, 2),
                idx,
                block,
            )
        )
        idx += 1

    for placement in image_placements:
        combined.append(
            (
                placement.page_number,
                placement.column_index,
                round(placement.bbox.y0, 2),
                round(placement.bbox.x0, 2),
                idx,
                placement,
            )
        )
        idx += 1

    combined.sort(key=lambda entry: (entry[0], entry[1], entry[2], entry[3], entry[4]))
    return [entry[5] for entry in combined]


def assemble_chapters(flow_items: Sequence[FlowItem]) -> list[Chapter]:
    if not flow_items:
        return [Chapter(title=None, level=1, blocks=[])]

    detected_headings = [b for b in flow_items if isinstance(b, DetectedHeading)]
    if not detected_headings:
        domain_blocks = [_to_domain_block(item) for item in flow_items]
        return [Chapter(title=None, level=1, blocks=domain_blocks)]

    chapter_level = min(h.level for h in detected_headings)
    chapters: list[Chapter] = []
    current_title: str | None = None
    current_level: int = 1
    current_blocks: list[Block] = []
    current_page: int | None = None
    current_has_body = False
    has_started_chapter = False

    for item in flow_items:
        domain_block = _to_domain_block(item)
        if isinstance(item, DetectedHeading) and item.level == chapter_level:
            if has_started_chapter and not current_has_body and item.page_number == current_page:
                current_blocks.append(domain_block)
                continue
            if has_started_chapter or current_blocks:
                chapters.append(
                    Chapter(
                        title=current_title,
                        level=current_level,
                        blocks=current_blocks,
                    )
                )
            current_title = item.text
            current_level = item.level
            current_blocks = [domain_block]
            current_page = item.page_number
            current_has_body = False
            has_started_chapter = True
        else:
            current_blocks.append(domain_block)
            if not isinstance(item, DetectedHeading):
                current_has_body = True

    if has_started_chapter or current_blocks:
        chapters.append(
            Chapter(
                title=current_title,
                level=current_level,
                blocks=current_blocks,
            )
        )

    return chapters


def build_document_from_pages(
    pages: Sequence[ExtractedPage],
    metadata: Metadata,
    warnings: Sequence[str] = (),
    *,
    assets: Mapping[str, ImageAsset] | None = None,
    image_placements: Sequence[ExtractedImagePlacement] = (),
    clean_headers_footers: bool = True,
    merge_across_pages: bool = True,
    min_heading_confidence: float = DEFAULT_MIN_HEADING_CONFIDENCE,
) -> Document:
    working_pages = filter_headers_and_footers(pages) if clean_headers_footers else list(pages)
    reconstructed = reconstruct_blocks_from_pages(
        working_pages,
        clean_headers_footers=False,
        merge_across_pages=merge_across_pages,
    )
    classified = classify_headings(
        reconstructed,
        min_confidence=min_heading_confidence,
    )
    flow_items = interleave_blocks_and_images(classified, image_placements)
    chapters = assemble_chapters(flow_items)
    return Document(
        metadata=metadata,
        chapters=chapters,
        warnings=list(warnings),
        assets=dict(assets) if assets is not None else {},
    )


def format_ocr_warning(ocr_pages: Sequence[int]) -> str | None:
    if not ocr_pages:
        return None
    pages_display = ", ".join(str(p) for p in ocr_pages)
    return (
        f"OCR aplicado na(s) página(s) {pages_display}; "
        "o reconhecimento óptico pode introduzir imprecisões textuais."
    )


def run_document_pipeline(
    pdf_path: Path | str,
    *,
    language_override: str | None = None,
    ocr_mode: OcrMode | str = OcrMode.NEVER,
    debug: bool = False,
    min_heading_confidence: float = DEFAULT_MIN_HEADING_CONFIDENCE,
) -> PipelineArtifacts:
    path = Path(pdf_path)
    inspection = inspect_pdf(path, debug=debug)

    cleaned_override = language_override.strip() if language_override is not None else ""
    resolved_language = cleaned_override if cleaned_override else inspection.language

    extracted_pages, ocr_pages = extract_pdf_pages_with_ocr(
        path,
        order_layout=True,
        ocr_mode=str(OcrMode.from_value(ocr_mode)),
        language=resolved_language,
        debug=debug,
    )
    cleaned_pages = filter_headers_and_footers(extracted_pages)
    reconstructed_blocks = reconstruct_blocks_from_pages(
        cleaned_pages,
        clean_headers_footers=False,
        merge_across_pages=True,
    )
    classified_blocks = classify_headings(
        reconstructed_blocks,
        min_confidence=min_heading_confidence,
    )
    image_extraction = extract_pdf_images(path, debug=debug)
    flow_items = interleave_blocks_and_images(
        classified_blocks,
        image_extraction.all_placements,
    )
    chapters = assemble_chapters(flow_items)

    metadata = Metadata(
        title=inspection.title,
        author=inspection.author,
        language=resolved_language,
        identifier=inspection.identifier,
    )

    combined_warnings = [*inspection.warnings, *image_extraction.warnings]
    ocr_warn = format_ocr_warning(ocr_pages)
    if ocr_warn is not None:
        combined_warnings.append(ocr_warn)

    document = Document(
        metadata=metadata,
        chapters=chapters,
        warnings=combined_warnings,
        assets=dict(image_extraction.assets),
    )

    return PipelineArtifacts(
        inspection=inspection,
        extracted_pages=extracted_pages,
        cleaned_pages=cleaned_pages,
        reconstructed_blocks=reconstructed_blocks,
        classified_blocks=classified_blocks,
        document=document,
        image_extraction=image_extraction,
    )


def _resolve_debug_base_dir(
    pdf_path: Path,
    output_path: Path | None,
    base_dir: Path | str | None,
) -> Path:
    if base_dir is not None:
        return Path(base_dir)
    env_dir = os.environ.get(ENV_ALQ_DEBUG_DIR, "").strip()
    if env_dir:
        return Path(env_dir)
    if output_path is not None:
        return output_path.parent / ".debug"
    return pdf_path.parent / ".debug"


def write_debug_artifacts(
    artifacts: PipelineArtifacts,
    pdf_path: Path | str,
    *,
    output_path: Path | str | None = None,
    base_dir: Path | str | None = None,
    logs: Sequence[str] = (),
) -> Path:
    resolved_pdf = Path(pdf_path)
    resolved_output = Path(output_path) if output_path is not None else None
    root_debug_dir = _resolve_debug_base_dir(resolved_pdf, resolved_output, base_dir)

    safe_stem = _SAFE_STEM_RE.sub("_", resolved_pdf.stem).strip("._-") or "document"
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    run_dir = root_debug_dir / f"{safe_stem}-{timestamp}-{uuid.uuid4().hex[:6]}"
    while run_dir.exists():
        run_dir = root_debug_dir / f"{safe_stem}-{timestamp}-{uuid.uuid4().hex[:6]}"

    run_dir.mkdir(parents=True, exist_ok=False)

    inspection_payload = artifacts.inspection.to_dict()
    (run_dir / "inspection.json").write_text(
        json.dumps(inspection_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    extracted_payload = {
        "pages": [page.to_dict() for page in artifacts.extracted_pages],
        "image_extraction": artifacts.image_extraction.to_dict(),
    }
    (run_dir / "extracted.json").write_text(
        json.dumps(extracted_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    normalized_payload = {
        "cleaned_pages": [page.to_dict() for page in artifacts.cleaned_pages],
        "reconstructed_blocks": [block.to_dict() for block in artifacts.reconstructed_blocks],
        "classified_blocks": [block.to_dict() for block in artifacts.classified_blocks],
    }
    (run_dir / "normalized.json").write_text(
        json.dumps(normalized_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    document_payload = artifacts.document.to_dict()
    (run_dir / "document.json").write_text(
        json.dumps(document_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    warnings_payload = {
        "warnings": list(artifacts.document.warnings),
        "count": len(artifacts.document.warnings),
    }
    (run_dir / "warnings.json").write_text(
        json.dumps(warnings_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    raw_block_count = sum(len(p.blocks) for p in artifacts.extracted_pages)
    cleaned_block_count = sum(len(p.blocks) for p in artifacts.cleaned_pages)
    log_lines: list[str] = [
        f"timestamp_utc={timestamp}",
        f"input={resolved_pdf}",
        f"output={resolved_output if resolved_output is not None else ''}",
        f"pages={artifacts.inspection.pages}",
        f"raw_blocks={raw_block_count}",
        f"cleaned_blocks={cleaned_block_count}",
        f"reconstructed_blocks={len(artifacts.reconstructed_blocks)}",
        f"classified_blocks={len(artifacts.classified_blocks)}",
        f"chapters={len(artifacts.document.chapters)}",
        f"paragraphs={artifacts.document.paragraph_count}",
        f"headings={artifacts.document.heading_count}",
        f"images={artifacts.document.image_count}",
        f"warnings_count={len(artifacts.document.warnings)}",
        *[str(line) for line in logs],
    ]
    (run_dir / "logs.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    return run_dir


__all__ = [
    "ENV_ALQ_DEBUG_DIR",
    "FlowItem",
    "PipelineArtifacts",
    "assemble_chapters",
    "build_document_from_pages",
    "format_ocr_warning",
    "interleave_blocks_and_images",
    "run_document_pipeline",
    "write_debug_artifacts",
]
