from __future__ import annotations

import unicodedata
from pathlib import Path

import pymupdf

from alq.pdf.text_extractor import (
    BoundingBox,
    ExtractedBlock,
    ExtractedLine,
    ExtractedPage,
    ExtractedSpan,
    extract_pdf_pages,
)
from alq.processing import (
    ReconstructedList,
    ReconstructedParagraph,
    filter_headers_and_footers,
    is_isolated_page_number,
    join_hyphenated_lines,
    normalize_text,
    reconstruct_blocks_from_pages,
    reconstruct_page_blocks,
)


def _make_line(
    text: str,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    *,
    font_size: float = 11.0,
    font_name: str = "Helvetica",
    is_bold: bool = False,
    is_italic: bool = False,
) -> ExtractedLine:
    bbox = BoundingBox(x0, y0, x1, y1)
    span = ExtractedSpan(
        text=text,
        bbox=bbox,
        font_size=font_size,
        font_name=font_name,
        flags=16 if is_bold else 0,
        is_bold=is_bold,
        is_italic=is_italic,
    )
    return ExtractedLine(
        text=text,
        bbox=bbox,
        spans=[span],
        font_size=font_size,
        font_name=font_name,
        is_bold=is_bold,
        is_italic=is_italic,
        flags=16 if is_bold else 0,
    )


def _make_block(
    page_number: int,
    lines: list[ExtractedLine],
    *,
    extraction_order: int = 0,
    column_index: int = 0,
) -> ExtractedBlock:
    bbox = BoundingBox.merge([line.bbox for line in lines])
    first = lines[0]
    return ExtractedBlock(
        page_number=page_number,
        text="\n".join(line.text for line in lines),
        bbox=bbox,
        lines=lines,
        font_size=first.font_size,
        font_name=first.font_name,
        flags=first.flags,
        is_bold=first.is_bold,
        is_italic=first.is_italic,
        extraction_order=extraction_order,
        column_index=column_index,
    )


def test_normalize_text_nfc_invisible_chars_and_whitespace() -> None:
    decomposed = unicodedata.normalize(
        "NFD",
        "Conversão   de\u00a0texto\u200b \ufeff\x07limpo",
    )
    result = normalize_text(decomposed)
    assert result == "Conversão de texto limpo"
    assert unicodedata.is_normalized("NFC", result)


def test_isolated_page_number_detection() -> None:
    for sample in ["42", "- 42 -", "— 15 —", "Página 42", "Page 42", "42 / 200", "7 de 120"]:
        assert is_isolated_page_number(sample) is True

    for non_page in ["Capítulo 1", "1. Introdução", "Parágrafo com 42 palavras."]:
        assert is_isolated_page_number(non_page) is False


def test_scenario_1_paragraph_broken_across_multiple_lines(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paragrafo_multilinha.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 120), "Este é um parágrafo longo que foi quebrado", fontsize=11)
    page.insert_text((72, 134), "em três linhas consecutivas dentro do arquivo", fontsize=11)
    page.insert_text((72, 148), "PDF e precisa ser reconstruído integralmente.", fontsize=11)
    doc.save(str(pdf_path))
    doc.close()

    pages = extract_pdf_pages(pdf_path)
    blocks = reconstruct_blocks_from_pages(pages)

    assert len(blocks) == 1
    para = blocks[0]
    assert isinstance(para, ReconstructedParagraph)
    assert para.text == (
        "Este é um parágrafo longo que foi quebrado "
        "em três linhas consecutivas dentro do arquivo "
        "PDF e precisa ser reconstruído integralmente."
    )
    assert para.page_number == 1
    assert para.line_count == 3
    assert para.font_size == 11.0
    assert para.is_bold is False


def test_scenario_2_paragraphs_separated_by_vertical_space_and_indentation() -> None:
    lines = [
        _make_line("Primeiro parágrafo começa na margem padrão", 72.0, 100.0, 460.0, 114.0),
        _make_line("e termina na segunda linha com ponto final.", 72.0, 115.0, 430.0, 129.0),
        _make_line("Segundo parágrafo separado por espaço vertical", 72.0, 160.0, 470.0, 174.0),
        _make_line("contendo duas linhas seguidas.", 72.0, 175.0, 340.0, 189.0),
        _make_line(
            "Terceiro parágrafo separado por recuo de primeira linha", 96.0, 190.0, 480.0, 204.0
        ),
        _make_line("voltando para a margem esquerda na linha seguinte.", 72.0, 205.0, 450.0, 219.0),
    ]
    page = ExtractedPage(
        page_number=1,
        width=595.0,
        height=842.0,
        blocks=[_make_block(1, lines)],
    )

    reconstructed = reconstruct_page_blocks(page)
    assert len(reconstructed) == 3
    assert all(isinstance(b, ReconstructedParagraph) for b in reconstructed)
    assert [b.text for b in reconstructed] == [
        "Primeiro parágrafo começa na margem padrão e termina na segunda linha com ponto final.",
        "Segundo parágrafo separado por espaço vertical contendo duas linhas seguidas.",
        (
            "Terceiro parágrafo separado por recuo de primeira linha "
            "voltando para a margem esquerda na linha seguinte."
        ),
    ]


def test_scenario_3_unordered_and_ordered_lists_detection_and_grouping() -> None:
    lines = [
        _make_line("Requisitos do sistema:", 72.0, 100.0, 250.0, 114.0),
        _make_line("• Extrair texto estruturado com coordenadas", 72.0, 135.0, 420.0, 149.0),
        _make_line("• Detectar cabeçalhos e rodapés repetitivos", 72.0, 152.0, 420.0, 166.0),
        _make_line("• Reconstruir parágrafos quebrados em", 72.0, 169.0, 400.0, 183.0),
        _make_line("múltiplas linhas consecutivas.", 84.0, 184.0, 310.0, 198.0),
        _make_line("1. Validar arquivo de entrada PDF", 72.0, 230.0, 380.0, 244.0),
        _make_line("2. Processar blocos e capítulos", 72.0, 247.0, 360.0, 261.0),
        _make_line("3. Empacotar arquivo EPUB final", 72.0, 264.0, 370.0, 278.0),
    ]
    page = ExtractedPage(
        page_number=1,
        width=595.0,
        height=842.0,
        blocks=[_make_block(1, lines)],
    )

    reconstructed = reconstruct_page_blocks(page)
    assert len(reconstructed) == 3

    intro = reconstructed[0]
    assert isinstance(intro, ReconstructedParagraph)
    assert intro.text == "Requisitos do sistema:"

    unordered = reconstructed[1]
    assert isinstance(unordered, ReconstructedList)
    assert unordered.ordered is False
    assert unordered.items == [
        "Extrair texto estruturado com coordenadas",
        "Detectar cabeçalhos e rodapés repetitivos",
        "Reconstruir parágrafos quebrados em múltiplas linhas consecutivas.",
    ]

    ordered = reconstructed[2]
    assert isinstance(ordered, ReconstructedList)
    assert ordered.ordered is True
    assert ordered.items == [
        "Validar arquivo de entrada PDF",
        "Processar blocos e capítulos",
        "Empacotar arquivo EPUB final",
    ]


def test_scenario_4_end_of_line_dehyphenation_and_uppercase_preservation() -> None:
    joined_lower = join_hyphenated_lines(
        [
            "O módulo realiza a desife-",
            "nização cautelosa de palavras que-",
            "bradas no fim da linha.",
        ]
    )
    assert (
        joined_lower
        == "O módulo realiza a desifenização cautelosa de palavras quebradas no fim da linha."
    )

    joined_soft = join_hyphenated_lines("proces\u00ad", "samento automático")
    assert joined_soft == "processamento automático"

    joined_upper = join_hyphenated_lines(
        [
            "Estudo do período pré-",
            "Cambriano na região Sul-",
            "Americana com padrão UTF-",
            "8.",
        ]
    )
    assert (
        joined_upper == "Estudo do período pré-Cambriano na região Sul-Americana com padrão UTF-8."
    )


def test_scenario_5_and_6_cross_page_paragraph_merge_with_headers_and_footers_filtered(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "duas_paginas_com_cabecalho_rodape.pdf"
    doc = pymupdf.open()

    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((72, 40), "Arquitetura de Software — Edição 1", fontsize=9)
    page1.insert_text(
        (72, 720),
        "Este parágrafo inicia na parte inferior da primeira página e realiza a conver-",
        fontsize=11,
    )
    page1.insert_text((280, 810), "Página 1", fontsize=9)

    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((72, 40), "Arquitetura de Software — Edição 1", fontsize=9)
    page2.insert_text(
        (72, 130),
        "são fluida do texto ao atravessar a fronteira entre as duas páginas.",
        fontsize=11,
    )
    page2.insert_text((280, 810), "Página 2", fontsize=9)

    doc.save(str(pdf_path))
    doc.close()

    extracted_pages = extract_pdf_pages(pdf_path)
    cleaned_pages = filter_headers_and_footers(extracted_pages)
    assert len(cleaned_pages[0].blocks) == 1
    assert len(cleaned_pages[1].blocks) == 1

    reconstructed = reconstruct_blocks_from_pages(extracted_pages)
    assert len(reconstructed) == 1
    merged_para = reconstructed[0]
    assert isinstance(merged_para, ReconstructedParagraph)
    assert merged_para.text == (
        "Este parágrafo inicia na parte inferior da primeira página e realiza a conversão "
        "fluida do texto ao atravessar a fronteira entre as duas páginas."
    )
    assert merged_para.page_number == 1
    assert merged_para.end_page_number == 2


def test_different_columns_are_never_merged_into_same_paragraph() -> None:
    left_block = _make_block(
        1,
        [_make_line("Texto da coluna esquerda sem ponto final", 60.0, 120.0, 260.0, 134.0)],
        extraction_order=0,
        column_index=0,
    )
    right_block = _make_block(
        1,
        [_make_line("continuação aparente mas na coluna direita.", 320.0, 120.0, 520.0, 134.0)],
        extraction_order=1,
        column_index=1,
    )
    page = ExtractedPage(
        page_number=1,
        width=595.0,
        height=842.0,
        blocks=[left_block, right_block],
    )

    reconstructed = reconstruct_page_blocks(page)
    assert len(reconstructed) == 2
    assert reconstructed[0].column_index == 0
    assert reconstructed[1].column_index == 1
