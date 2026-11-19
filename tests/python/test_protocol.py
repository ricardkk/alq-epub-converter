from __future__ import annotations

import json

import pytest

from alq.cli import main
from alq.errors import (
    AlqWorkerError,
    EpubBuildError,
    EpubValidationError,
    ErrorCode,
    NoExtractableTextError,
    PdfOpenError,
    PdfPasswordRequiredError,
    TextExtractionError,
)
from alq.protocol import (
    SCHEMA_VERSION,
    build_error_response,
    build_error_response_from_exception,
    build_stub_response,
    emit_debug,
    emit_stage,
)


def test_contract_success_convert_has_all_section_5_fields() -> None:
    resp = build_stub_response(
        command="convert",
        input_path="/tmp/entrada.pdf",
        output_path="/tmp/saida.epub",
        language="pt-BR",
    )
    raw = resp.to_json()
    assert "\n" not in raw

    data = json.loads(raw)
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["status"] == "success"
    assert data["input"] == "/tmp/entrada.pdf"
    assert data["output"] == "/tmp/saida.epub"
    assert isinstance(data["warnings"], list)
    assert isinstance(data["duration_ms"], int)

    meta = data["metadata"]
    assert set(meta.keys()) == {"title", "author", "language", "identifier"}
    assert meta["language"] == "pt-BR"

    stats = data["statistics"]
    assert set(stats.keys()) == {
        "pages",
        "pages_with_text",
        "pages_without_text",
        "chapters",
        "paragraphs",
        "images",
        "page_dimensions",
        "needs_ocr",
    }
    assert stats["pages"] == 1
    assert stats["pages_with_text"] == 1
    assert stats["pages_without_text"] == 0
    assert stats["page_dimensions"] == {"width": 595.0, "height": 842.0}
    assert stats["needs_ocr"] is False


def test_contract_success_inspect_omits_output() -> None:
    resp = build_stub_response(
        command="inspect",
        input_path="/tmp/inspecao.pdf",
    )
    data = json.loads(resp.to_json())
    assert data["schema_version"] == 1
    assert data["status"] == "success"
    assert data["input"] == "/tmp/inspecao.pdf"
    assert "output" not in data
    assert "metadata" in data
    assert "statistics" in data


@pytest.mark.parametrize(
    ("exc", "expected_code"),
    [
        (PdfOpenError("Arquivo PDF truncado ou corrompido."), "PDF_OPEN_FAILED"),
        (PdfPasswordRequiredError("Documento criptografado."), "PDF_PASSWORD_REQUIRED"),
        (NoExtractableTextError("PDF escaneado sem OCR."), "NO_EXTRACTABLE_TEXT"),
        (TextExtractionError("Erro ao ler página 3."), "TEXT_EXTRACTION_FAILED"),
        (EpubBuildError("Falha ao escrever container.xml."), "EPUB_BUILD_FAILED"),
        (EpubValidationError("OPF inválido."), "EPUB_VALIDATION_FAILED"),
        (AlqWorkerError(ErrorCode.INVALID_INPUT, "Entrada inválida."), "INVALID_INPUT"),
        (AlqWorkerError(ErrorCode.INPUT_NOT_FOUND, "Não encontrado."), "INPUT_NOT_FOUND"),
    ],
)
def test_domain_exceptions_serialize_to_error_contract(
    exc: AlqWorkerError,
    expected_code: str,
) -> None:
    resp = build_error_response_from_exception(exc)
    data = json.loads(resp.to_json())
    assert data["schema_version"] == 1
    assert data["status"] == "error"
    assert data["error"]["code"] == expected_code
    assert data["error"]["message"] == exc.message
    assert data["warnings"] == []


def test_error_response_with_warnings_and_hint() -> None:
    resp = build_error_response(
        ErrorCode.NO_EXTRACTABLE_TEXT,
        "Texto ausente.",
        warnings=["Página 1 contém apenas imagem."],
        hint="Aplique OCR antes de converter.",
    )
    data = json.loads(resp.to_json())
    assert data["status"] == "error"
    assert data["error"]["code"] == "NO_EXTRACTABLE_TEXT"
    assert data["error"]["hint"] == "Aplique OCR antes de converter."
    assert data["warnings"] == ["Página 1 contém apenas imagem."]


def test_cli_simulate_error_via_flag_and_env(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code = main(["convert", "doc.pdf", "--simulate-error", "PDF_OPEN_FAILED"])
    assert code == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.out
    payload = json.loads(captured.out.strip())
    assert payload["schema_version"] == 1
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "PDF_OPEN_FAILED"

    monkeypatch.setenv("ALQ_SIMULATE_ERROR", "PDF_PASSWORD_REQUIRED")
    monkeypatch.setenv("PDF2EPUB_DEBUG", "1")
    code_env = main(["inspect", "doc.pdf", "--json"])
    assert code_env == 1
    captured_env = capsys.readouterr()
    assert "Traceback" not in captured_env.out
    payload_env = json.loads(captured_env.out.strip())
    assert payload_env["status"] == "error"
    assert payload_env["error"]["code"] == "PDF_PASSWORD_REQUIRED"
    assert "DEBUG:" in captured_env.err


def test_emit_stage_and_debug_write_only_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_stage(2, 6, "Normalizando parágrafos")
    emit_debug("Bloco descartado por ruído", enabled=True)
    emit_debug("Mensagem suprimida", enabled=False)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "STAGE:2/6:Normalizando parágrafos" in captured.err
    assert "DEBUG: Bloco descartado por ruído" in captured.err
    assert "Mensagem suprimida" not in captured.err
