"""Camada de leitura e extração de conteúdo de arquivos PDF via PyMuPDF."""

from __future__ import annotations

from alq.pdf.reader import (
    PdfInspectionResult,
    configure_mupdf_quiet,
    inspect_pdf,
    open_pdf,
)

__all__ = [
    "PdfInspectionResult",
    "configure_mupdf_quiet",
    "inspect_pdf",
    "open_pdf",
]
