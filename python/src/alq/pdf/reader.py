from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf

from alq.errors import PdfOpenError, PdfPasswordRequiredError
from alq.protocol import (
    SCHEMA_VERSION,
    DocumentMetadataPayload,
    DocumentStatisticsPayload,
    PageDimensionsPayload,
    WorkerResponsePayload,
    emit_debug,
)


def configure_mupdf_quiet() -> None:
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)


configure_mupdf_quiet()


def _normalize_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


def _extract_language(doc: pymupdf.Document, raw_metadata: dict[str, Any]) -> str:
    meta_lang = _normalize_optional_str(raw_metadata.get("language"))
    if meta_lang is not None:
        return meta_lang

    try:
        catalog_xref = int(doc.pdf_catalog())
        if catalog_xref > 0:
            key_type, key_val = doc.xref_get_key(catalog_xref, "Lang")
            if key_type == "string":
                catalog_lang = _normalize_optional_str(key_val)
                if catalog_lang is not None:
                    return catalog_lang
    except Exception:
        pass

    return "und"


def _extract_identifier(raw_metadata: dict[str, Any]) -> str | None:
    direct_id = _normalize_optional_str(raw_metadata.get("identifier"))
    if direct_id is not None:
        return direct_id
    return None


@dataclass(frozen=True, slots=True)
class PdfInspectionResult:
    path: Path
    pages: int
    pages_with_text: int
    pages_without_text: int
    images: int
    page_dimensions: PageDimensionsPayload
    title: str | None = None
    author: str | None = None
    language: str = "und"
    identifier: str | None = None
    needs_ocr: bool = False
    warnings: list[str] = field(default_factory=list)
    duration_ms: int = 0

    @property
    def metadata(self) -> DocumentMetadataPayload:
        return DocumentMetadataPayload(
            title=self.title,
            author=self.author,
            language=self.language,
            identifier=self.identifier,
        )

    @property
    def statistics(self) -> DocumentStatisticsPayload:
        return DocumentStatisticsPayload(
            pages=self.pages,
            pages_with_text=self.pages_with_text,
            pages_without_text=self.pages_without_text,
            chapters=0,
            paragraphs=0,
            images=self.images,
            page_dimensions=self.page_dimensions,
            needs_ocr=self.needs_ocr,
        )

    def to_worker_response(self, *, input_display: str | None = None) -> WorkerResponsePayload:
        return WorkerResponsePayload(
            schema_version=SCHEMA_VERSION,
            status="success",
            command="inspect",
            input=input_display if input_display is not None else str(self.path),
            output=None,
            metadata=self.metadata,
            statistics=self.statistics,
            warnings=list(self.warnings),
            duration_ms=self.duration_ms,
            error=None,
        )


@contextmanager
def open_pdf(path: Path | str) -> Iterator[pymupdf.Document]:
    configure_mupdf_quiet()
    pymupdf.TOOLS.reset_mupdf_warnings()
    pdf_path = Path(path)

    if not pdf_path.exists():
        raise PdfOpenError(
            f"Não foi possível abrir o arquivo PDF '{pdf_path}': arquivo não encontrado.",
            hint="Verifique se o caminho do arquivo PDF informado existe.",
        )

    if not pdf_path.is_file():
        raise PdfOpenError(
            f"Não foi possível abrir '{pdf_path}': o caminho informado não é um arquivo regular.",
            hint="Informe o caminho para um arquivo PDF válido.",
        )

    doc: pymupdf.Document | None = None
    try:
        try:
            doc = pymupdf.open(pdf_path)
        except Exception as exc:
            raise PdfOpenError(
                f"Não foi possível abrir ou ler o arquivo PDF '{pdf_path}': {exc}",
                hint="Verifique se o arquivo é um PDF válido e não está corrompido ou truncado.",
            ) from exc

        if bool(doc.needs_pass):
            raise PdfPasswordRequiredError(
                f"O arquivo PDF '{pdf_path}' está protegido por senha e não pode ser processado.",
                hint="Remova a senha do documento PDF antes de executar o alq.",
            )

        if not bool(doc.is_pdf):
            raise PdfOpenError(
                f"O arquivo '{pdf_path}' não possui uma estrutura interna de documento PDF válida.",
                hint="Informe um arquivo PDF válido.",
            )

        try:
            page_count = int(doc.page_count)
        except Exception as exc:
            raise PdfOpenError(
                f"Não foi possível ler a contagem de páginas do PDF '{pdf_path}': {exc}",
                hint="O arquivo PDF pode estar corrompido.",
            ) from exc

        if page_count <= 0:
            raise PdfOpenError(
                f"O arquivo PDF '{pdf_path}' não contém páginas válidas (0 páginas).",
                hint="Verifique se o documento PDF não está vazio.",
            )

        yield doc
    finally:
        if doc is not None and not doc.is_closed:
            doc.close()


def inspect_pdf(path: Path | str, *, debug: bool = False) -> PdfInspectionResult:
    start_ns = time.perf_counter_ns()
    pdf_path = Path(path)

    with open_pdf(pdf_path) as doc:
        total_pages = int(doc.page_count)
        raw_meta: dict[str, Any] = dict(doc.metadata) if doc.metadata is not None else {}

        title = _normalize_optional_str(raw_meta.get("title"))
        author = _normalize_optional_str(raw_meta.get("author"))
        language = _extract_language(doc, raw_meta)
        identifier = _extract_identifier(raw_meta)

        pages_with_text = 0
        pages_without_text = 0
        pages_without_text_with_images = 0
        total_images = 0
        first_page_dimensions: PageDimensionsPayload | None = None

        try:
            for page_idx in range(total_pages):
                page = doc.load_page(page_idx)
                rect = page.rect
                width = round(float(rect.width), 2)
                height = round(float(rect.height), 2)
                if first_page_dimensions is None:
                    first_page_dimensions = PageDimensionsPayload(width=width, height=height)

                page_text = str(page.get_text("text")).strip()
                has_text = bool(page_text)
                if has_text:
                    pages_with_text += 1
                else:
                    pages_without_text += 1

                image_refs = page.get_images(full=False)
                page_image_count = len(image_refs)
                total_images += page_image_count

                if not has_text and page_image_count > 0:
                    pages_without_text_with_images += 1
        except Exception as exc:
            raise PdfOpenError(
                f"Falha ao ler as páginas do arquivo PDF '{pdf_path}': {exc}",
                hint="O arquivo PDF pode estar truncado ou com objetos internos corrompidos.",
            ) from exc

        warnings: list[str] = []
        mupdf_warn_raw = str(pymupdf.TOOLS.mupdf_warnings() or "").strip()
        if mupdf_warn_raw:
            for line in mupdf_warn_raw.splitlines():
                clean_line = line.strip()
                if clean_line:
                    emit_debug(f"MuPDF warning: {clean_line}", enabled=debug)
                    warnings.append(f"Aviso de estrutura PDF: {clean_line}")

        needs_ocr = False
        if pages_with_text == 0:
            needs_ocr = True
            warnings.append(
                "Nenhum texto extraível encontrado; o documento parece ser escaneado e exigirá OCR."
            )
        elif pages_without_text > 0:
            if pages_without_text_with_images > 0:
                warnings.append(
                    f"{pages_without_text} de {total_pages} página(s) não possuem texto extraível "
                    f"({pages_without_text_with_images} página(s) sem texto contêm imagens; "
                    "possível necessidade parcial de OCR)."
                )
            else:
                warnings.append(
                    f"{pages_without_text} de {total_pages} página(s) não possuem texto extraível."
                )

        elapsed_ms = max(0, int((time.perf_counter_ns() - start_ns) / 1_000_000))
        resolved_dimensions = first_page_dimensions or PageDimensionsPayload(
            width=595.0, height=842.0
        )

        emit_debug(
            f"Inspeção concluída: pages={total_pages}, with_text={pages_with_text}, "
            f"without_text={pages_without_text}, images={total_images}, needs_ocr={needs_ocr}",
            enabled=debug,
        )

        return PdfInspectionResult(
            path=pdf_path,
            pages=total_pages,
            pages_with_text=pages_with_text,
            pages_without_text=pages_without_text,
            images=total_images,
            page_dimensions=resolved_dimensions,
            title=title,
            author=author,
            language=language,
            identifier=identifier,
            needs_ocr=needs_ocr,
            warnings=warnings,
            duration_ms=int(elapsed_ms),
        )
