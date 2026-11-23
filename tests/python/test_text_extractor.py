from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from alq.errors import ErrorCode, NoExtractableTextError
from alq.pdf.layout import (
    is_two_column_layout,
    order_extracted_pages,
    order_page_blocks,
)
from alq.pdf.text_extractor import (
    PYMUPDF_BOLD_FLAG,
    PYMUPDF_ITALIC_FLAG,
    BoundingBox,
    ExtractedBlock,
    ExtractedLine,
    ExtractedPage,
    ExtractedSpan,
    detect_is_bold,
    detect_is_italic,
    extract_page_from_dict,
    extract_pdf_pages,
    extract_text_blocks,
)


def test_bounding_box_properties_and_serialization() -> None:
    bbox = BoundingBox.from_sequence([72.0, 100.5, 272.0, 130.5])
    assert bbox.x0 == 72.0
    assert bbox.y0 == 100.5
    assert bbox.x1 == 272.0
    assert bbox.y1 == 130.5
    assert bbox.width == 200.0
    assert bbox.height == 30.0
    assert bbox.center_x == 172.0
    assert bbox.center_y == 115.5
    assert bbox.to_dict() == {
        "x0": 72.0,
        "y0": 100.5,
        "x1": 272.0,
        "y1": 130.5,
    }

    merged = BoundingBox.merge([bbox, BoundingBox(50.0, 90.0, 300.0, 150.0)])
    assert merged == BoundingBox(50.0, 90.0, 300.0, 150.0)


def test_detect_bold_and_italic_via_flags_and_font_names() -> None:
    assert detect_is_bold("Helvetica", PYMUPDF_BOLD_FLAG) is True
    assert detect_is_bold("TimesNewRomanPS-BoldMT", 0) is True
    assert detect_is_bold("Arial-Black", 0) is True
    assert detect_is_bold("Futura-Heavy", 0) is True
    assert detect_is_bold("Helvetica", 0) is False

    assert detect_is_italic("Helvetica", PYMUPDF_ITALIC_FLAG) is True
    assert detect_is_italic("Times-Italic", 0) is True
    assert detect_is_italic("Helvetica-Oblique", 0) is True
    assert detect_is_italic("Helvetica", 0) is False


def test_extract_pdf_preserves_typography_bbox_lines_and_order(tmp_path: Path) -> None:
    pdf_path = tmp_path / "tipografia.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 80), "Capítulo 1: Introdução", fontname="hebo", fontsize=18)
    page.insert_text((72, 130), "Nota preliminar em itálico", fontname="heit", fontsize=13)
    page.insert_text(
        (72, 180),
        "Primeiro parágrafo do corpo de texto.\nSegunda linha contínua do mesmo bloco.",
        fontname="helv",
        fontsize=11,
    )
    page.insert_text((72, 250), "Destaque simultâneo", fontname="hebi", fontsize=12)
    doc.save(str(pdf_path))
    doc.close()

    pages = extract_pdf_pages(pdf_path, debug=True)
    assert len(pages) == 1

    extracted_page = pages[0]
    assert extracted_page.page_number == 1
    assert extracted_page.width == 595.0
    assert extracted_page.height == 842.0
    assert len(extracted_page.blocks) == 4

    heading_block = extracted_page.blocks[0]
    assert heading_block.page_number == 1
    assert heading_block.text == "Capítulo 1: Introdução"
    assert heading_block.font_size == 18.0
    assert "Bold" in heading_block.font_name
    assert bool(heading_block.flags & PYMUPDF_BOLD_FLAG) is True
    assert heading_block.is_bold is True
    assert heading_block.is_italic is False
    assert heading_block.extraction_order == 0
    assert heading_block.column_index == 0
    assert heading_block.bbox.x0 == pytest.approx(72.0, abs=1.0)
    assert heading_block.bbox.width > 50.0
    assert heading_block.bbox.height > 10.0

    italic_block = extracted_page.blocks[1]
    assert italic_block.text == "Nota preliminar em itálico"
    assert italic_block.font_size == 13.0
    assert "Oblique" in italic_block.font_name or "Italic" in italic_block.font_name
    assert bool(italic_block.flags & PYMUPDF_ITALIC_FLAG) is True
    assert italic_block.is_bold is False
    assert italic_block.is_italic is True
    assert italic_block.extraction_order == 1

    body_block = extracted_page.blocks[2]
    assert "Primeiro parágrafo do corpo de texto." in body_block.text
    assert "Segunda linha contínua do mesmo bloco." in body_block.text
    assert len(body_block.lines) == 2
    assert body_block.lines[0].text == "Primeiro parágrafo do corpo de texto."
    assert body_block.lines[1].text == "Segunda linha contínua do mesmo bloco."
    assert body_block.font_size == 11.0
    assert body_block.is_bold is False
    assert body_block.is_italic is False
    assert body_block.extraction_order == 2

    bold_italic_block = extracted_page.blocks[3]
    assert bold_italic_block.text == "Destaque simultâneo"
    assert bold_italic_block.font_size == 12.0
    assert bold_italic_block.is_bold is True
    assert bold_italic_block.is_italic is True
    assert bold_italic_block.extraction_order == 3

    page_dict = extracted_page.to_dict()
    assert page_dict["page_number"] == 1
    assert len(page_dict["blocks"]) == 4


def test_extract_page_from_dict_ignores_empty_whitespace_and_image_blocks() -> None:
    raw_page_dict = {
        "width": 595.0,
        "height": 842.0,
        "blocks": [
            {
                "type": 1,
                "bbox": (50.0, 50.0, 200.0, 200.0),
            },
            {
                "type": 0,
                "bbox": (72.0, 100.0, 200.0, 115.0),
                "lines": [
                    {
                        "bbox": (72.0, 100.0, 200.0, 115.0),
                        "spans": [
                            {
                                "text": "   \n\t  ",
                                "bbox": (72.0, 100.0, 200.0, 115.0),
                                "size": 12.0,
                                "font": "Helvetica",
                                "flags": 0,
                            }
                        ],
                    }
                ],
            },
            {
                "type": 0,
                "bbox": (72.0, 140.0, 300.0, 155.0),
                "lines": [
                    {
                        "bbox": (72.0, 140.0, 100.0, 155.0),
                        "spans": [
                            {
                                "text": "   ",
                                "bbox": (72.0, 140.0, 100.0, 155.0),
                                "size": 12.0,
                                "font": "Helvetica",
                                "flags": 0,
                            }
                        ],
                    },
                    {
                        "bbox": (72.0, 140.0, 300.0, 155.0),
                        "spans": [
                            {
                                "text": "  ",
                                "bbox": (72.0, 140.0, 80.0, 155.0),
                                "size": 12.0,
                                "font": "Helvetica",
                                "flags": 0,
                            },
                            {
                                "text": "Texto válido preservado",
                                "bbox": (80.0, 140.0, 300.0, 155.0),
                                "size": 12.0,
                                "font": "Times-BoldItalic",
                                "flags": 0,
                            },
                        ],
                    },
                ],
            },
        ],
    }

    page = extract_page_from_dict(raw_page_dict, page_number=1)
    assert len(page.blocks) == 1
    block = page.blocks[0]
    assert block.text == "Texto válido preservado"
    assert block.extraction_order == 0
    assert block.is_bold is True
    assert block.is_italic is True
    assert len(block.lines) == 1
    assert len(block.lines[0].spans) == 1


def test_single_column_layout_orders_by_vertical_position_and_preserves_extraction_order(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "coluna_simples_fora_de_ordem.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 300), "Terceiro bloco no final da página")
    page.insert_text((72, 90), "Primeiro bloco no topo da página")
    page.insert_text((72, 190), "Segundo bloco no meio da página")
    doc.save(str(pdf_path))
    doc.close()

    raw_pages = extract_pdf_pages(pdf_path, order_layout=False)
    assert [b.extraction_order for b in raw_pages[0].blocks] == [0, 1, 2]
    assert is_two_column_layout(raw_pages[0].blocks, raw_pages[0].width) is False

    ordered_pages = order_extracted_pages(raw_pages)
    ordered_blocks = ordered_pages[0].blocks
    assert [b.text for b in ordered_blocks] == [
        "Primeiro bloco no topo da página",
        "Segundo bloco no meio da página",
        "Terceiro bloco no final da página",
    ]
    assert [b.column_index for b in ordered_blocks] == [0, 0, 0]
    assert [b.extraction_order for b in ordered_blocks] == [1, 2, 0]


def test_two_column_layout_assigns_column_index_and_orders_left_then_right(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "duas_colunas.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)

    page.insert_textbox(
        pymupdf.Rect(50, 80, 270, 140),
        "Coluna esquerda parágrafo 1.\nContinuação esquerda 1.",
    )
    page.insert_textbox(
        pymupdf.Rect(320, 80, 540, 140),
        "Coluna direita parágrafo 1.\nContinuação direita 1.",
    )
    page.insert_textbox(
        pymupdf.Rect(50, 180, 270, 240),
        "Coluna esquerda parágrafo 2.",
    )
    page.insert_textbox(
        pymupdf.Rect(320, 180, 540, 240),
        "Coluna direita parágrafo 2.",
    )
    doc.save(str(pdf_path))
    doc.close()

    blocks = extract_text_blocks(pdf_path)
    assert len(blocks) == 4
    assert [b.column_index for b in blocks] == [0, 0, 1, 1]
    assert "Coluna esquerda parágrafo 1." in blocks[0].text
    assert "Coluna esquerda parágrafo 2." in blocks[1].text
    assert "Coluna direita parágrafo 1." in blocks[2].text
    assert "Coluna direita parágrafo 2." in blocks[3].text


def test_order_page_blocks_directly_on_synthetic_two_column_blocks() -> None:
    def make_block(
        text: str,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        order: int,
    ) -> ExtractedBlock:
        bbox = BoundingBox(x0, y0, x1, y1)
        span = ExtractedSpan(
            text=text,
            bbox=bbox,
            font_size=11.0,
            font_name="Helvetica",
            flags=0,
            is_bold=False,
            is_italic=False,
        )
        line = ExtractedLine(
            text=text,
            bbox=bbox,
            spans=[span],
            font_size=11.0,
            font_name="Helvetica",
            is_bold=False,
            is_italic=False,
        )
        return ExtractedBlock(
            page_number=1,
            text=text,
            bbox=bbox,
            lines=[line],
            font_size=11.0,
            font_name="Helvetica",
            flags=0,
            is_bold=False,
            is_italic=False,
            extraction_order=order,
        )

    raw_blocks = [
        make_block("Direita Topo", 320.0, 100.0, 520.0, 130.0, 0),
        make_block("Esquerda Base", 60.0, 220.0, 260.0, 250.0, 1),
        make_block("Direita Base", 320.0, 220.0, 520.0, 250.0, 2),
        make_block("Esquerda Topo", 60.0, 100.0, 260.0, 130.0, 3),
    ]

    page = ExtractedPage(page_number=1, width=595.0, height=842.0, blocks=raw_blocks)
    ordered = order_page_blocks(page.blocks, page.width)

    assert [b.text for b in ordered] == [
        "Esquerda Topo",
        "Esquerda Base",
        "Direita Topo",
        "Direita Base",
    ]
    assert [b.column_index for b in ordered] == [0, 0, 1, 1]
    assert [b.extraction_order for b in ordered] == [3, 1, 0, 2]


def test_pdf_without_extractable_text_raises_no_extractable_text_error(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "sem_texto.pdf"
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    doc.new_page(width=595, height=842)
    doc.save(str(pdf_path))
    doc.close()

    with pytest.raises(NoExtractableTextError) as exc_info:
        extract_pdf_pages(pdf_path)

    assert exc_info.value.code == ErrorCode.NO_EXTRACTABLE_TEXT

    with pytest.raises(NoExtractableTextError):
        extract_text_blocks(pdf_path)


def test_is_two_column_layout_false_for_spanning_body_with_centered_marker() -> None:
    def make_block(
        text: str,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        order: int,
    ) -> ExtractedBlock:
        bbox = BoundingBox(x0, y0, x1, y1)
        span = ExtractedSpan(
            text=text,
            bbox=bbox,
            font_size=12.0,
            font_name="Times",
            flags=0,
            is_bold=False,
            is_italic=False,
        )
        line = ExtractedLine(
            text=text,
            bbox=bbox,
            spans=[span],
            font_size=12.0,
            font_name="Times",
            is_bold=False,
            is_italic=False,
        )
        return ExtractedBlock(
            page_number=3,
            bbox=bbox,
            text=text,
            lines=[line],
            font_size=12.0,
            font_name="Times",
            flags=0,
            is_bold=False,
            is_italic=False,
            extraction_order=order,
        )

    blocks = [
        make_block("The Metamorphosis", 52.2, 26.3, 133.1, 37.3, 0),
        make_block("I", 190.2, 62.3, 199.6, 75.8, 1),
        make_block(
            "One morning, as Gregor Samsa was waking up from anxious dreams, he discovered that "
            "in bed he had been changed into a monstrous verminous bug.",
            52.2,
            84.0,
            336.4,
            180.0,
            2,
        ),
        make_block("3 of 105", 52.2, 560.0, 95.0, 571.0, 3),
    ]

    assert is_two_column_layout(blocks, 388.8) is False
    ordered = order_page_blocks(blocks, 388.8)
    assert [b.text for b in ordered[:3]] == [
        "The Metamorphosis",
        "I",
        "One morning, as Gregor Samsa was waking up from anxious dreams, he discovered that "
        "in bed he had been changed into a monstrous verminous bug.",
    ]
    assert [b.column_index for b in ordered] == [0, 0, 0, 0]


def test_is_garbled_text_detects_corrupted_glyph_codes() -> None:
    from alq.pdf.reader import is_garbled_text

    garbled_control = '\x01\x02\x03!\x04"\x05#\x06\x07\x08\x09\x0b\x0c\x0e\x0fABB ( BC9D'
    garbled_symbols = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~!\"#$%&'()*+,-./:;<=>?@"
    valid_pt = "Uma noite destas, vindo da cidade para o Engenho Novo, encontrei no trem."
    valid_short = "CAPÍTULO I"

    assert is_garbled_text(garbled_control) is True
    assert is_garbled_text(garbled_symbols) is True
    assert is_garbled_text(valid_pt) is False
    assert is_garbled_text(valid_short) is False
