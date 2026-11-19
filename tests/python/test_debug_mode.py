from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

from alq.cli import main

EXPECTED_DEBUG_FILES: set[str] = {
    "inspection.json",
    "extracted.json",
    "normalized.json",
    "document.json",
    "warnings.json",
    "logs.txt",
}


def _create_sample_pdf(pdf_path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 85), "CAPÍTULO 1: Diagnóstico", fontname="hebo", fontsize=18)
    page.insert_text(
        (72, 135),
        "Conteúdo textual para verificação completa dos artefatos de debug.",
        fontname="helv",
        fontsize=11,
    )
    doc.set_metadata({"title": "Livro Diagnóstico", "author": "Equipe ALQ"})
    doc.save(str(pdf_path))
    doc.close()


def test_convert_with_debug_flag_creates_all_diagnostic_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pdf_path = tmp_path / "meu_livro.pdf"
    epub_path = tmp_path / "meu_livro.epub"
    _create_sample_pdf(pdf_path)

    exit_code = main(
        [
            "convert",
            str(pdf_path),
            "--output",
            str(epub_path),
            "--debug",
        ]
    )
    assert exit_code == 0
    _ = capsys.readouterr()

    debug_root = tmp_path / ".debug"
    assert debug_root.is_dir()

    run_dirs = [p for p in debug_root.iterdir() if p.is_dir()]
    assert len(run_dirs) == 1

    run_dir = run_dirs[0]
    assert run_dir.name.startswith("meu_livro-")

    file_names = {p.name for p in run_dir.iterdir() if p.is_file()}
    assert file_names == EXPECTED_DEBUG_FILES

    inspection_data = json.loads((run_dir / "inspection.json").read_text(encoding="utf-8"))
    assert inspection_data["metadata"]["title"] == "Livro Diagnóstico"
    assert inspection_data["statistics"]["pages"] == 1

    extracted_data = json.loads((run_dir / "extracted.json").read_text(encoding="utf-8"))
    assert len(extracted_data["pages"]) == 1
    assert len(extracted_data["pages"][0]["blocks"]) == 2

    normalized_data = json.loads((run_dir / "normalized.json").read_text(encoding="utf-8"))
    assert "cleaned_pages" in normalized_data
    assert "reconstructed_blocks" in normalized_data
    assert "classified_blocks" in normalized_data

    document_data = json.loads((run_dir / "document.json").read_text(encoding="utf-8"))
    assert document_data["metadata"]["title"] == "Livro Diagnóstico"
    assert len(document_data["chapters"]) == 1

    warnings_data = json.loads((run_dir / "warnings.json").read_text(encoding="utf-8"))
    assert "warnings" in warnings_data
    assert warnings_data["count"] == len(warnings_data["warnings"])

    logs_text = (run_dir / "logs.txt").read_text(encoding="utf-8")
    assert "STAGE 1/6:" in logs_text
    assert "STAGE 6/6:" in logs_text
    assert "chapters=1" in logs_text


def test_consecutive_debug_runs_do_not_overwrite_each_other(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pdf_path = tmp_path / "obra.pdf"
    epub_path = tmp_path / "obra.epub"
    _create_sample_pdf(pdf_path)

    for _ in range(2):
        code = main(
            [
                "convert",
                str(pdf_path),
                "--output",
                str(epub_path),
                "--debug",
                "--overwrite",
            ]
        )
        assert code == 0
        _ = capsys.readouterr()

    debug_root = tmp_path / ".debug"
    run_dirs = [p for p in debug_root.iterdir() if p.is_dir()]
    assert len(run_dirs) == 2
    assert run_dirs[0].name != run_dirs[1].name
    for run_dir in run_dirs:
        assert {p.name for p in run_dir.iterdir() if p.is_file()} == EXPECTED_DEBUG_FILES


def test_normal_convert_without_debug_does_not_create_debug_folder(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALQ_DEBUG", raising=False)
    monkeypatch.delenv("PDF2EPUB_DEBUG", raising=False)

    pdf_path = tmp_path / "normal.pdf"
    epub_path = tmp_path / "normal.epub"
    _create_sample_pdf(pdf_path)

    code = main(
        [
            "convert",
            str(pdf_path),
            "--output",
            str(epub_path),
        ]
    )
    assert code == 0
    _ = capsys.readouterr()

    assert epub_path.is_file()
    assert not (tmp_path / ".debug").exists()
