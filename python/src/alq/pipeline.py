from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alq.domain.blocks import Block, Heading, ListBlock, Paragraph
from alq.domain.document import Chapter, Document, ImageAsset
from alq.domain.metadata import Metadata
from alq.pdf.reader import PdfInspectionResult, inspect_pdf
from alq.pdf.text_extractor import ExtractedPage, extract_pdf_pages
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


@dataclass(frozen=True, slots=True)
class PipelineArtifacts:
    inspection: PdfInspectionResult
    extracted_pages: list[ExtractedPage]
    cleaned_pages: list[ExtractedPage]
    reconstructed_blocks: list[ReconstructedCandidateBlock]
    classified_blocks: list[ClassifiedBlock]
    document: Document

    def to_dict(self) -> dict[str, Any]:
        return {
            "extracted_pages": [page.to_dict() for page in self.extracted_pages],
            "cleaned_pages": [page.to_dict() for page in self.cleaned_pages],
            "reconstructed_blocks": [block.to_dict() for block in self.reconstructed_blocks],
            "classified_blocks": [block.to_dict() for block in self.classified_blocks],
            "document": self.document.to_dict(),
        }


def _to_domain_block(item: ClassifiedBlock) -> Block:
    if isinstance(item, DetectedHeading):
        return Heading(text=item.text, level=item.level)
    if isinstance(item, ReconstructedList):
        return ListBlock(ordered=item.ordered, items=list(item.items))
    if isinstance(item, ReconstructedParagraph):
        return Paragraph(text=item.text)
    raise TypeError(f"Unsupported block type: {type(item)!r}")


def assemble_chapters(classified_blocks: Sequence[ClassifiedBlock]) -> list[Chapter]:
    if not classified_blocks:
        return [Chapter(title=None, level=1, blocks=[])]

    detected_headings = [b for b in classified_blocks if isinstance(b, DetectedHeading)]
    if not detected_headings:
        domain_blocks = [_to_domain_block(item) for item in classified_blocks]
        return [Chapter(title=None, level=1, blocks=domain_blocks)]

    chapter_level = min(h.level for h in detected_headings)
    chapters: list[Chapter] = []
    current_title: str | None = None
    current_level: int = 1
    current_blocks: list[Block] = []
    has_started_chapter = False

    for item in classified_blocks:
        domain_block = _to_domain_block(item)
        if isinstance(item, DetectedHeading) and item.level == chapter_level:
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
            has_started_chapter = True
        else:
            current_blocks.append(domain_block)

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
    chapters = assemble_chapters(classified)
    return Document(
        metadata=metadata,
        chapters=chapters,
        warnings=list(warnings),
        assets=dict(assets) if assets is not None else {},
    )


def run_document_pipeline(
    pdf_path: Path | str,
    *,
    language_override: str | None = None,
    debug: bool = False,
    min_heading_confidence: float = DEFAULT_MIN_HEADING_CONFIDENCE,
) -> PipelineArtifacts:
    path = Path(pdf_path)
    inspection = inspect_pdf(path, debug=debug)
    extracted_pages = extract_pdf_pages(path, order_layout=True, debug=debug)
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
    chapters = assemble_chapters(classified_blocks)

    cleaned_override = language_override.strip() if language_override is not None else ""
    resolved_language = cleaned_override if cleaned_override else inspection.language

    metadata = Metadata(
        title=inspection.title,
        author=inspection.author,
        language=resolved_language,
        identifier=inspection.identifier,
    )

    document = Document(
        metadata=metadata,
        chapters=chapters,
        warnings=list(inspection.warnings),
    )

    return PipelineArtifacts(
        inspection=inspection,
        extracted_pages=extracted_pages,
        cleaned_pages=cleaned_pages,
        reconstructed_blocks=reconstructed_blocks,
        classified_blocks=classified_blocks,
        document=document,
    )


__all__ = [
    "PipelineArtifacts",
    "assemble_chapters",
    "build_document_from_pages",
    "run_document_pipeline",
]
