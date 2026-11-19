from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

from alq.cli import main
from alq.errors import ErrorCode, PdfOpenError, PdfPasswordRequiredError
from alq.pdf.reader import inspect_pdf, open_pdf


def _make_sample_png_bytes() -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 24, 24), False)
    pix.set_rect(pix.irect, (180, 90, 45))
    return bytes(pix.tobytes("png"))


def test_inspect_textual_pdf_with_metadata(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pdf_path = tmp_path / "textual.pdf"
    doc = pymupdf.open()
    for idx in range(1, 4):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"Capítulo {idx}\nParágrafo de texto da página {idx}.")
    doc.set_metadata(
        {
            "title": "Dom Casmurro",
            "author": "Machado de Assis",
        }
    )
    doc.save(str(pdf_path))
    doc.close()

    result = inspect_pdf(pdf_path)
    assert result.path == pdf_path
    assert result.pages == 3
    assert result.pages_with_text == 3
    assert result.pages_without_text == 0
    assert result.images == 0
    assert result.title == "Dom Casmurro"
    assert result.author == "Machado de Assis"
    assert result.language == "und"
    assert result.identifier is None
    assert result.page_dimensions.width == 595.0
    assert result.page_dimensions.height == 842.0
    assert result.needs_ocr is False
    assert result.warnings == []
    assert result.duration_ms >= 0

    exit_code = main(["inspect", str(pdf_path), "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())
    assert payload["schema_version"] == 1
    assert payload["status"] == "success"
    assert payload["command"] == "inspect"
    assert payload["metadata"]["title"] == "Dom Casmurro"
    assert payload["metadata"]["author"] == "Machado de Assis"
    assert payload["statistics"]["pages"] == 3
    assert payload["statistics"]["pages_with_text"] == 3
    assert payload["statistics"]["pages_without_text"] == 0
    assert payload["statistics"]["images"] == 0
    assert payload["statistics"]["needs_ocr"] is False
    assert "STAGE:1/2:" in captured.err
    assert "STAGE:2/2:" in captured.err


def test_inspect_pdf_without_metadata_does_not_invent_fields(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sem_metadados.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "Conteúdo textual simples sem metadados.")
    doc.set_metadata({"title": "   ", "author": ""})
    doc.save(str(pdf_path))
    doc.close()

    result = inspect_pdf(pdf_path)
    assert result.pages == 1
    assert result.pages_with_text == 1
    assert result.pages_without_text == 0
    assert result.title is None
    assert result.author is None
    assert result.language == "und"
    assert result.identifier is None
    assert result.page_dimensions.width == 612.0
    assert result.page_dimensions.height == 792.0
    assert result.needs_ocr is False


def test_inspect_scanned_pdf_detects_ocr_need_and_counts_images(tmp_path: Path) -> None:
    pdf_path = tmp_path / "escaneado.pdf"
    png_bytes = _make_sample_png_bytes()

    doc = pymupdf.open()
    for _ in range(2):
        page = doc.new_page(width=595, height=842)
        page.insert_image(pymupdf.Rect(50, 50, 300, 300), stream=png_bytes)
    doc.save(str(pdf_path))
    doc.close()

    result = inspect_pdf(pdf_path)
    assert result.pages == 2
    assert result.pages_with_text == 0
    assert result.pages_without_text == 2
    assert result.images >= 1
    assert result.images == 2
    assert result.needs_ocr is True
    assert any("OCR" in w for w in result.warnings)


def test_inspect_mixed_pdf_reports_partial_pages_without_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "misto.pdf"
    png_bytes = _make_sample_png_bytes()

    doc = pymupdf.open()
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((72, 72), "Página 1 com camada de texto extraível.")

    page2 = doc.new_page(width=595, height=842)
    page2.insert_image(pymupdf.Rect(50, 50, 250, 250), stream=png_bytes)

    doc.new_page(width=595, height=842)
    doc.save(str(pdf_path))
    doc.close()

    result = inspect_pdf(pdf_path)
    assert result.pages == 3
    assert result.pages_with_text == 1
    assert result.pages_without_text == 2
    assert result.images == 1
    assert result.needs_ocr is False
    assert len(result.warnings) == 1
    assert "2 de 3" in result.warnings[0]
    assert "OCR" in result.warnings[0]


def test_inspect_password_protected_pdf_raises_password_required(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pdf_path = tmp_path / "protegido.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Conteúdo confidencial.")
    doc.save(
        str(pdf_path),
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw="segredo",
        owner_pw="dono",
    )
    doc.close()

    with pytest.raises(PdfPasswordRequiredError) as exc_info:
        inspect_pdf(pdf_path)
    assert exc_info.value.code == ErrorCode.PDF_PASSWORD_REQUIRED
    assert "senha" in exc_info.value.message.lower()

    exit_code = main(["inspect", str(pdf_path), "--json"])
    assert exit_code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())
    assert payload["schema_version"] == 1
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "PDF_PASSWORD_REQUIRED"


def test_inspect_corrupted_pdf_raises_pdf_open_error_without_stdout_pollution(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corrupted_path = tmp_path / "corrompido.pdf"
    corrupted_path.write_bytes(b"%PDF-1.4\ncorrompido")

    with pytest.raises(PdfOpenError) as exc_info:
        inspect_pdf(corrupted_path)
    assert exc_info.value.code == ErrorCode.PDF_OPEN_FAILED

    captured_direct = capsys.readouterr()
    assert captured_direct.out == ""

    exit_code = main(["inspect", str(corrupted_path), "--json"])
    assert exit_code == 1
    captured_cli = capsys.readouterr()
    payload = json.loads(captured_cli.out.strip())
    assert payload["schema_version"] == 1
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "PDF_OPEN_FAILED"


def test_open_pdf_context_manager_closes_document_even_on_exception(tmp_path: Path) -> None:
    pdf_path = tmp_path / "contexto.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Teste de fechamento seguro.")
    doc.save(str(pdf_path))
    doc.close()

    leaked_ref: pymupdf.Document | None = None
    with pytest.raises(RuntimeError, match="erro intencional"):
        with open_pdf(pdf_path) as opened_doc:
            leaked_ref = opened_doc
            assert not opened_doc.is_closed
            raise RuntimeError("erro intencional")

    assert leaked_ref is not None
    assert leaked_ref.is_closed


def test_cli_invalid_arguments_emit_structured_invalid_input_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["inspect", "--flag-inexistente"])
    assert exit_code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())
    assert payload["schema_version"] == 1
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "INVALID_INPUT"
