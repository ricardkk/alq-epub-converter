from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

from alq.domain import Chapter, Document, Heading, ImageAsset, ImageBlock, Metadata, Paragraph
from alq.epub import build_epub, ensure_valid_epub, validate_epub_file
from alq.errors import EpubValidationError, ErrorCode


def _build_sample_epub(epub_path: Path) -> Path:
    asset = ImageAsset(
        asset_id="img_001",
        media_type="image/png",
        data=b"\x89PNG\r\n\x1a\nfake_png_bytes",
        filename="images/img_001.png",
        width=100,
        height=100,
        page_number=1,
    )
    doc = Document(
        metadata=Metadata(
            title="Livro Validado",
            author="Autor",
            language="pt-BR",
            identifier="urn:uuid:12345678-1234-5678-1234-567812345678",
        ),
        chapters=[
            Chapter(
                title="Capítulo 1",
                level=1,
                blocks=[
                    Heading("Capítulo 1", level=1),
                    Paragraph("Texto de teste válido."),
                    ImageBlock(asset_id="img_001", alt_text="Figura 1"),
                ],
            )
        ],
        assets={"img_001": asset},
    )
    return build_epub(doc, epub_path)


def test_valid_built_epub_passes_internal_validation(tmp_path: Path) -> None:
    epub_path = _build_sample_epub(tmp_path / "valido.epub")

    report = ensure_valid_epub(epub_path, run_epubcheck=False)
    assert report.valid is True
    assert report.errors == []
    assert report.epubcheck_executed is False
    assert report.to_dict()["valid"] is True


def test_missing_or_empty_or_non_zip_file_fails_validation(tmp_path: Path) -> None:
    missing_path = tmp_path / "inexistente.epub"
    with pytest.raises(EpubValidationError) as exc_missing:
        ensure_valid_epub(missing_path)
    assert exc_missing.value.code == ErrorCode.EPUB_VALIDATION_FAILED

    empty_path = tmp_path / "vazio.epub"
    empty_path.write_bytes(b"")
    with pytest.raises(EpubValidationError) as exc_empty:
        ensure_valid_epub(empty_path)
    assert exc_empty.value.code == ErrorCode.EPUB_VALIDATION_FAILED

    non_zip_path = tmp_path / "nao_zip.epub"
    non_zip_path.write_bytes(b"isto nao e um arquivo zip")
    with pytest.raises(EpubValidationError) as exc_non_zip:
        ensure_valid_epub(non_zip_path)
    assert exc_non_zip.value.code == ErrorCode.EPUB_VALIDATION_FAILED


def test_zip_missing_container_or_opf_fails_validation(tmp_path: Path) -> None:
    no_container_path = tmp_path / "sem_container.epub"
    with zipfile.ZipFile(no_container_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")

    with pytest.raises(EpubValidationError) as exc_no_container:
        ensure_valid_epub(no_container_path)
    assert "container.xml" in exc_no_container.value.message

    no_opf_path = tmp_path / "sem_opf.epub"
    container_xml = (
        "<?xml version='1.0' encoding='utf-8'?>"
        "<container version='1.0'>"
        "<rootfiles>"
        "<rootfile full-path='EPUB/content.opf' media-type='application/oebps-package+xml'/>"
        "</rootfiles>"
        "</container>"
    )
    with zipfile.ZipFile(no_opf_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)

    with pytest.raises(EpubValidationError) as exc_no_opf:
        ensure_valid_epub(no_opf_path)
    assert "EPUB/content.opf" in exc_no_opf.value.message


def test_epub_with_malformed_xhtml_fails_validation(tmp_path: Path) -> None:
    base_epub = _build_sample_epub(tmp_path / "base.epub")
    corrupted_epub = tmp_path / "xhtml_invalido.epub"

    with (
        zipfile.ZipFile(base_epub, "r") as src_zf,
        zipfile.ZipFile(corrupted_epub, "w") as dst_zf,
    ):
        for item in src_zf.infolist():
            if item.filename == "EPUB/chapter_001.xhtml":
                dst_zf.writestr(item, "<html><body><p>Tag nao fechada</body></html>")
            else:
                dst_zf.writestr(item, src_zf.read(item.filename))

    with pytest.raises(EpubValidationError) as exc_info:
        ensure_valid_epub(corrupted_epub, run_epubcheck=False)
    assert exc_info.value.code == ErrorCode.EPUB_VALIDATION_FAILED
    assert "EPUB/chapter_001.xhtml" in exc_info.value.message


def test_epub_with_broken_image_or_manifest_reference_fails_validation(
    tmp_path: Path,
) -> None:
    base_epub = _build_sample_epub(tmp_path / "base_img.epub")
    missing_img_epub = tmp_path / "sem_imagem.epub"

    with (
        zipfile.ZipFile(base_epub, "r") as src_zf,
        zipfile.ZipFile(missing_img_epub, "w") as dst_zf,
    ):
        for item in src_zf.infolist():
            if item.filename == "EPUB/images/img_001.png":
                continue
            dst_zf.writestr(item, src_zf.read(item.filename))

    report = validate_epub_file(missing_img_epub, run_epubcheck=False)
    assert report.valid is False
    assert any("EPUB/images/img_001.png" in err for err in report.errors)

    with pytest.raises(EpubValidationError) as exc_info:
        ensure_valid_epub(missing_img_epub, run_epubcheck=False)
    assert exc_info.value.code == ErrorCode.EPUB_VALIDATION_FAILED


def test_optional_epubcheck_integration_when_absent_and_when_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epub_path = _build_sample_epub(tmp_path / "check.epub")

    monkeypatch.setattr("alq.epub.validator.shutil.which", lambda _cmd: None)
    report_no_bin = validate_epub_file(epub_path, run_epubcheck=True)
    assert report_no_bin.valid is True
    assert report_no_bin.epubcheck_executed is False

    monkeypatch.setattr("alq.epub.validator.shutil.which", lambda _cmd: "/usr/bin/epubcheck")
    monkeypatch.setattr(
        "alq.epub.validator.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["epubcheck"],
            returncode=1,
            stdout="",
            stderr="ERROR(RSC-005): erro simulado do epubcheck",
        ),
    )
    report_failed_bin = validate_epub_file(epub_path, run_epubcheck=True)
    assert report_failed_bin.valid is False
    assert report_failed_bin.epubcheck_executed is True
    assert any("EPUBCheck" in err for err in report_failed_bin.errors)
