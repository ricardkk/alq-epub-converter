from __future__ import annotations

from alq.pdf.image_extractor import (
    DEFAULT_MIN_IMAGE_AREA,
    DEFAULT_MIN_IMAGE_HEIGHT,
    DEFAULT_MIN_IMAGE_WIDTH,
    ExtractedImagePlacement,
    ImageExtractionResult,
    extract_pdf_images,
    normalize_image_bytes,
)
from alq.pdf.layout import (
    is_two_column_layout,
    order_extracted_pages,
    order_page_blocks,
)
from alq.pdf.reader import (
    PdfInspectionResult,
    configure_mupdf_quiet,
    inspect_pdf,
    open_pdf,
)
from alq.pdf.text_extractor import (
    PYMUPDF_BOLD_FLAG,
    PYMUPDF_ITALIC_FLAG,
    BoundingBox,
    ExtractedBlock,
    ExtractedLine,
    ExtractedPage,
    ExtractedSpan,
    detect_is_bold,
    detect_is_italic,
    extract_page,
    extract_page_from_dict,
    extract_pdf_pages,
    extract_text_blocks,
)

__all__ = [
    "DEFAULT_MIN_IMAGE_AREA",
    "DEFAULT_MIN_IMAGE_HEIGHT",
    "DEFAULT_MIN_IMAGE_WIDTH",
    "PYMUPDF_BOLD_FLAG",
    "PYMUPDF_ITALIC_FLAG",
    "BoundingBox",
    "ExtractedBlock",
    "ExtractedImagePlacement",
    "ExtractedLine",
    "ExtractedPage",
    "ExtractedSpan",
    "ImageExtractionResult",
    "PdfInspectionResult",
    "configure_mupdf_quiet",
    "detect_is_bold",
    "detect_is_italic",
    "extract_page",
    "extract_page_from_dict",
    "extract_pdf_images",
    "extract_pdf_pages",
    "extract_text_blocks",
    "inspect_pdf",
    "is_two_column_layout",
    "normalize_image_bytes",
    "open_pdf",
    "order_extracted_pages",
    "order_page_blocks",
]
