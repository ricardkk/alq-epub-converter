from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pymupdf
import pytest

from alq.cli import main
from alq.domain import Heading, Paragraph
from alq.errors import ErrorCode, TextExtractionError
from alq.pdf import (
    OcrMode,
    extract_pdf_pages_with_ocr,
    resolve_tesseract_language,
)
from alq.pipeline import run_document_pipeline


def test_ocr_mode_and_language_mapping() -> None:
    assert OcrMode.from_value("auto") == OcrMode.AUTO
    assert OcrMode.from_value("ALWAYS") == OcrMode.ALWAYS
    assert OcrMode.from_value("never") == OcrMode.NEVER
    assert OcrMode.from_value(None) == OcrMode.NEVER

    with pytest.raises(TextExtractionError):
        OcrMode.from_value("invalido")

    assert resolve_tesseract_language("pt-BR") == "por"
    assert resolve_tesseract_language("pt") == "por"
    assert resolve_tesseract_language("en-US") == "eng"
    assert resolve_tesseract_language("es") == "spa"
    assert resolve_tesseract_language("und") == "por+eng"


def test_ocr_auto_skips_tesseract_on_pages_with_native_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "nativo.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Texto nativo que não deve sofrer OCR.")
    doc.save(str(pdf_path))
    doc.close()

    monkeypatch.setattr("alq.pdf.ocr.find_tesseract_binary", lambda: None)

    pages, ocr_pages = extract_pdf_pages_with_ocr(pdf_path, ocr_mode="auto")
    assert len(pages) == 1
    assert ocr_pages == []
    assert pages[0].blocks[0].text == "Texto nativo que não deve sofrer OCR."


def test_ocr_auto_and_always_extract_text_from_scanned_page_and_build_valid_epub(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pdf_path = tmp_path / "escaneado.pdf"
    epub_path = tmp_path / "escaneado.epub"

    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    doc.save(str(pdf_path))
    doc.close()

    fake_ocr_text = (
        "CAPÍTULO 1: Documento Digitalizado\n\n"
        "Primeiro parágrafo reconhecido pelo motor óptico com que-\n"
        "bra de linha reconstruída automaticamente.\n\n"
        "Segundo parágrafo separado por linha em branco."
    )

    monkeypatch.setattr("alq.pdf.ocr.find_tesseract_binary", lambda: "/usr/bin/tesseract")
    monkeypatch.setattr(
        "alq.pdf.ocr._run_tesseract_command",
        lambda _bin, png_bytes, _lang, _dpi: subprocess.CompletedProcess(
            args=["tesseract"],
            returncode=0,
            stdout=fake_ocr_text.encode("utf-8") if png_bytes.startswith(b"\x89PNG") else b"",
            stderr=b"",
        ),
    )

    artifacts = run_document_pipeline(pdf_path, ocr_mode=OcrMode.AUTO, language_override="pt-BR")
    document = artifacts.document
    assert len(document.chapters) == 1
    assert document.chapters[0].title == "CAPÍTULO 1: Documento Digitalizado"
    assert document.chapters[0].blocks == [
        Heading("CAPÍTULO 1: Documento Digitalizado", level=1),
        Paragraph(
            "Primeiro parágrafo reconhecido pelo motor óptico com quebra "
            "de linha reconstruída automaticamente."
        ),
        Paragraph("Segundo parágrafo separado por linha em branco."),
    ]
    assert any("OCR aplicado na(s) página(s) 1" in w for w in document.warnings)

    exit_code = main(
        [
            "convert",
            str(pdf_path),
            "--output",
            str(epub_path),
            "--ocr",
            "always",
            "--language",
            "pt-BR",
        ]
    )
    assert exit_code == 0
    assert epub_path.is_file()
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())
    assert payload["status"] == "success"
    assert payload["statistics"]["chapters"] == 1
    assert payload["statistics"]["paragraphs"] == 2
    assert any("OCR aplicado na(s) página(s) 1" in w for w in payload["warnings"])


def test_ocr_raises_text_extraction_error_when_tesseract_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pdf_path = tmp_path / "sem_tesseract.pdf"
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    doc.save(str(pdf_path))
    doc.close()

    monkeypatch.setattr("alq.pdf.ocr.find_tesseract_binary", lambda: None)

    with pytest.raises(TextExtractionError) as exc_info:
        extract_pdf_pages_with_ocr(pdf_path, ocr_mode="auto")
    assert exc_info.value.code == ErrorCode.TEXT_EXTRACTION_FAILED
    assert "tesseract" in exc_info.value.message.lower()

    exit_code = main(["convert", str(pdf_path), "--ocr", "always"])
    assert exit_code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "TEXT_EXTRACTION_FAILED"
