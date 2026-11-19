from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

import alq
from alq.cli import main
from alq.protocol import SCHEMA_VERSION, build_stub_response


def test_package_version() -> None:
    assert alq.__version__ == "0.1.0"


def test_cli_no_args_returns_zero() -> None:
    assert main([]) == 0


def test_cli_convert_outputs_valid_json_v1_and_creates_epub(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pdf_path = tmp_path / "exemplo.pdf"
    epub_path = tmp_path / "exemplo.epub"

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 80), "CAPÍTULO 1: Introdução", fontname="hebo", fontsize=18)
    page.insert_text((72, 130), "Parágrafo de exemplo para conversão real em EPUB.", fontsize=11)
    doc.save(str(pdf_path))
    doc.close()

    exit_code = main(
        [
            "convert",
            str(pdf_path),
            "--output",
            str(epub_path),
            "--language",
            "pt-BR",
            "--debug",
            "--overwrite",
        ]
    )
    assert exit_code == 0
    assert epub_path.is_file()
    assert epub_path.stat().st_size > 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "success"
    assert payload["command"] == "convert"
    assert payload["input"] == str(pdf_path)
    assert payload["output"] == str(epub_path)
    assert payload["metadata"]["language"] == "pt-BR"
    assert payload["statistics"]["pages"] == 1
    assert payload["statistics"]["chapters"] == 1
    assert payload["statistics"]["paragraphs"] == 1
    assert "STAGE:1/6:" in captured.err
    assert "STAGE:6/6:" in captured.err


def test_cli_inspect_outputs_valid_json_v1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pdf_path = tmp_path / "relatorio.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "Relatório técnico de inspeção.")
    doc.save(str(pdf_path))
    doc.close()

    exit_code = main(["inspect", str(pdf_path), "--json"])
    assert exit_code == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "success"
    assert payload["command"] == "inspect"
    assert payload["input"] == str(pdf_path)
    assert payload["statistics"]["pages"] == 1
    assert payload["statistics"]["pages_with_text"] == 1
    assert "output" not in payload


def test_build_stub_response_serialization() -> None:
    resp = build_stub_response(
        command="convert",
        input_path="livro.pdf",
        output_path="livro.epub",
        language="en",
    )
    parsed = json.loads(resp.to_json())
    assert parsed["schema_version"] == 1
    assert parsed["status"] == "success"
    assert parsed["metadata"]["language"] == "en"
    assert parsed["statistics"]["needs_ocr"] is False
