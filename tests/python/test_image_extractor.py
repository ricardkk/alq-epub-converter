from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from PIL import Image

from alq.domain import Heading, ImageBlock, Paragraph
from alq.epub import build_epub
from alq.pdf import extract_pdf_images, normalize_image_bytes
from alq.pipeline import run_document_pipeline


def _create_image_bytes(
    width: int,
    height: int,
    *,
    img_format: str = "PNG",
    color: tuple[int, int, int] = (40, 120, 200),
) -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format=img_format)
    return buf.getvalue()


def test_extract_valid_image_interleaves_in_document_and_embeds_in_epub(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "com_imagem.pdf"
    epub_path = tmp_path / "com_imagem.epub"
    png_bytes = _create_image_bytes(120, 90, img_format="PNG")

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 80), "CAPÍTULO 1: Ilustrações", fontname="hebo", fontsize=18)
    page.insert_text(
        (72, 130),
        "Parágrafo introdutório posicionado acima da figura.",
        fontname="helv",
        fontsize=11,
    )
    page.insert_image(pymupdf.Rect(72, 160, 272, 310), stream=png_bytes)
    page.insert_text(
        (72, 350),
        "Parágrafo explicativo posicionado abaixo da figura.",
        fontname="helv",
        fontsize=11,
    )
    doc.save(str(pdf_path))
    doc.close()

    img_result = extract_pdf_images(pdf_path, debug=True)
    assert len(img_result.assets) == 1
    assert "img_001" in img_result.assets
    asset = img_result.assets["img_001"]
    assert asset.media_type == "image/png"
    assert asset.filename == "images/img_001.png"
    assert asset.width == 120
    assert asset.height == 90
    assert len(img_result.all_placements) == 1

    artifacts = run_document_pipeline(pdf_path)
    document = artifacts.document
    assert document.image_count == 1
    assert len(document.chapters) == 1
    chapter_blocks = document.chapters[0].blocks
    assert len(chapter_blocks) == 4
    assert isinstance(chapter_blocks[0], Heading)
    assert isinstance(chapter_blocks[1], Paragraph)
    assert isinstance(chapter_blocks[2], ImageBlock)
    assert chapter_blocks[2].asset_id == "img_001"
    assert isinstance(chapter_blocks[3], Paragraph)

    build_epub(document, epub_path)
    with zipfile.ZipFile(epub_path, "r") as zf:
        assert "EPUB/images/img_001.png" in zf.namelist()
        ch_xhtml = zf.read("EPUB/chapter_001.xhtml").decode("utf-8")
        assert 'src="images/img_001.png"' in ch_xhtml


def test_tiny_decorative_images_are_filtered_out(tmp_path: Path) -> None:
    pdf_path = tmp_path / "icone_decorativo.pdf"
    tiny_png = _create_image_bytes(8, 8, img_format="PNG")
    normal_png = _create_image_bytes(100, 80, img_format="PNG")

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 80), "Texto da página com ícone pequeno e imagem real.")
    page.insert_image(pymupdf.Rect(72, 100, 80, 108), stream=tiny_png)
    page.insert_image(pymupdf.Rect(72, 150, 272, 310), stream=normal_png)
    doc.save(str(pdf_path))
    doc.close()

    result = extract_pdf_images(pdf_path, debug=True)
    assert len(result.assets) == 1
    assert "img_001" in result.assets
    assert result.assets["img_001"].width == 100
    assert result.assets["img_001"].height == 80
    assert len(result.all_placements) == 1


def test_normalize_image_bytes_converts_non_epub_formats_to_png() -> None:
    bmp_bytes = _create_image_bytes(64, 48, img_format="BMP")
    norm_bytes, media_type, ext, width, height = normalize_image_bytes(bmp_bytes, "bmp")
    assert media_type == "image/png"
    assert ext == "png"
    assert width == 64
    assert height == 48
    with Image.open(io.BytesIO(norm_bytes)) as converted:
        assert converted.format == "PNG"
        assert converted.size == (64, 48)

    tiff_bytes = _create_image_bytes(50, 50, img_format="TIFF")
    _, tiff_media, tiff_ext, tiff_w, tiff_h = normalize_image_bytes(tiff_bytes, "tiff")
    assert tiff_media == "image/png"
    assert tiff_ext == "png"
    assert (tiff_w, tiff_h) == (50, 50)


def test_corrupted_image_stream_records_warning_without_aborting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "imagem_corrompida.pdf"
    png_bytes = _create_image_bytes(80, 80, img_format="PNG")

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 80), "Texto preservado mesmo com falha em imagem.")
    page.insert_image(pymupdf.Rect(72, 140, 200, 268), stream=png_bytes)
    doc.save(str(pdf_path))
    doc.close()

    def _broken_extract(_doc: Any, _xref: int) -> dict[str, Any]:
        return {"image": b"bytes_invalidos_nao_imagem", "ext": "png"}

    monkeypatch.setattr(
        "alq.pdf.image_extractor._extract_raw_image_dict",
        _broken_extract,
    )

    result = extract_pdf_images(pdf_path)
    assert result.assets == {}
    assert result.all_placements == []
    assert len(result.warnings) == 1
    assert "página 1" in result.warnings[0].lower()
