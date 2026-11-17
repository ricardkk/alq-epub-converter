"""Testes smoke para o worker Python `alq`."""

from __future__ import annotations

import json

import pytest

import alq
from alq.cli import main
from alq.protocol import SCHEMA_VERSION, build_stub_response


def test_package_version() -> None:
    """Verifica se o pacote `alq` é importável e expõe a versão esperada."""
    assert alq.__version__ == "0.1.0"


def test_cli_no_args_returns_zero() -> None:
    """Verifica que invocar `main([])` sem argumentos encerra com código 0."""
    assert main([]) == 0


def test_cli_convert_stub_outputs_valid_json_v1(capsys: pytest.CaptureFixture[str]) -> None:
    """Verifica que `alq convert` no worker Python emite Contrato JSON v1 válido no stdout."""
    exit_code = main(
        [
            "convert",
            "exemplo.pdf",
            "--output",
            "exemplo.epub",
            "--language",
            "pt-BR",
            "--debug",
            "--overwrite",
        ]
    )
    assert exit_code == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "success"
    assert payload["command"] == "convert"
    assert payload["input"] == "exemplo.pdf"
    assert payload["output"] == "exemplo.epub"
    assert payload["metadata"]["language"] == "pt-BR"
    assert payload["statistics"]["pages"] == 1
    assert "STAGE:1/2:" in captured.err
    assert "STAGE:2/2:" in captured.err


def test_cli_inspect_stub_outputs_valid_json_v1(capsys: pytest.CaptureFixture[str]) -> None:
    """Verifica que `alq inspect` no worker Python emite Contrato JSON v1 válido no stdout."""
    exit_code = main(["inspect", "relatorio.pdf", "--json"])
    assert exit_code == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "success"
    assert payload["command"] == "inspect"
    assert payload["input"] == "relatorio.pdf"
    assert "output" not in payload


def test_build_stub_response_serialization() -> None:
    """Verifica a serialização direta do envelope `WorkerResponsePayload`."""
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
