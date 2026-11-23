from __future__ import annotations

from pathlib import Path

import pymupdf

from alq.pdf.text_extractor import BoundingBox, extract_pdf_pages
from alq.processing import (
    DEFAULT_MIN_HEADING_CONFIDENCE,
    DetectedHeading,
    ReconstructedCandidateBlock,
    ReconstructedList,
    ReconstructedParagraph,
    classify_headings,
    compute_median_font_size,
    detect_headings,
    evaluate_heading_candidate,
    reconstruct_blocks_from_pages,
)


def _make_paragraph(
    text: str,
    *,
    font_size: float = 11.0,
    is_bold: bool = False,
    is_italic: bool = False,
    page_number: int = 1,
    line_count: int = 1,
) -> ReconstructedParagraph:
    return ReconstructedParagraph(
        text=text,
        page_number=page_number,
        bbox=BoundingBox(72.0, 100.0, 480.0, 115.0),
        font_size=font_size,
        font_name="Helvetica-Bold" if is_bold else "Helvetica",
        is_bold=is_bold,
        is_italic=is_italic,
        line_count=line_count,
    )


def test_numbered_and_keyword_headings_levels_and_confidence() -> None:
    blocks = [
        _make_paragraph("CAPÍTULO 1: Fundamentos", font_size=18.0, is_bold=True),
        _make_paragraph(
            "Este é um parágrafo regular do corpo do documento utilizado para "
            "estabelecer a mediana tipográfica de onze pontos no texto.",
            font_size=11.0,
        ),
        _make_paragraph("1 Introdução", font_size=15.0, is_bold=True),
        _make_paragraph("1.1 Subtítulo da Seção", font_size=13.0, is_bold=True),
        _make_paragraph("1.1.1 Tópico Específico", font_size=12.0, is_bold=True),
        _make_paragraph("CONCLUSÃO", font_size=16.0, is_bold=True),
    ]

    median = compute_median_font_size(blocks)
    assert median == 11.0

    headings = detect_headings(blocks)
    assert len(headings) == 5

    assert headings[0].text == "CAPÍTULO 1: Fundamentos"
    assert headings[0].level == 1
    assert headings[0].confidence >= DEFAULT_MIN_HEADING_CONFIDENCE

    assert headings[1].text == "1 Introdução"
    assert headings[1].level == 1
    assert headings[1].confidence >= DEFAULT_MIN_HEADING_CONFIDENCE

    assert headings[2].text == "1.1 Subtítulo da Seção"
    assert headings[2].level == 2
    assert headings[2].confidence >= DEFAULT_MIN_HEADING_CONFIDENCE

    assert headings[3].text == "1.1.1 Tópico Específico"
    assert headings[3].level == 3
    assert headings[3].confidence >= DEFAULT_MIN_HEADING_CONFIDENCE

    assert headings[4].text == "CONCLUSÃO"
    assert headings[4].level == 1
    assert headings[4].confidence >= DEFAULT_MIN_HEADING_CONFIDENCE
    assert headings[4].to_dict()["kind"] == "heading"


def test_unnumbered_headings_detected_by_font_size_hierarchy() -> None:
    blocks = [
        _make_paragraph("Arquitetura de Sistemas Distribuídos", font_size=18.0, is_bold=True),
        _make_paragraph(
            "O desenvolvimento de sistemas modernos exige comunicação estruturada "
            "entre processos independentes com validação rigorosa de contratos.",
            font_size=11.0,
        ),
        _make_paragraph("Camada de Transporte e Protocolo", font_size=14.5, is_bold=False),
        _make_paragraph(
            "Cada mensagem trafega serializada em formato compacto e determinístico "
            "para evitar ambiguidades na leitura dos dados.",
            font_size=11.0,
        ),
        _make_paragraph("Tratamento de Falhas", font_size=13.0, is_bold=True),
    ]

    classified = classify_headings(blocks)
    detected = [b for b in classified if isinstance(b, DetectedHeading)]
    assert len(detected) == 3

    assert detected[0].text == "Arquitetura de Sistemas Distribuídos"
    assert detected[0].level == 1
    assert detected[0].confidence >= DEFAULT_MIN_HEADING_CONFIDENCE

    assert detected[1].text == "Camada de Transporte e Protocolo"
    assert detected[1].level == 2
    assert detected[1].confidence >= DEFAULT_MIN_HEADING_CONFIDENCE

    assert detected[2].text == "Tratamento de Falhas"
    assert detected[2].level == 3
    assert detected[2].confidence >= DEFAULT_MIN_HEADING_CONFIDENCE


def test_rejects_false_positives_bold_sentences_long_blocks_and_dates() -> None:
    bold_sentence_with_period = _make_paragraph(
        "Esta frase está em negrito mas termina com ponto final.",
        font_size=11.0,
        is_bold=True,
    )
    bold_phrase_same_size = _make_paragraph(
        "Observação importante da equipe técnica",
        font_size=11.0,
        is_bold=True,
    )
    long_bold_large_paragraph = _make_paragraph(
        "Este é um parágrafo extremamente longo que foi formatado com fonte maior "
        "e estilo em negrito no início do documento original, porém contém muitas "
        "palavras e múltiplas linhas que descaracterizam qualquer título de capítulo.",
        font_size=16.0,
        is_bold=True,
        line_count=4,
    )
    sentence_starting_with_year = _make_paragraph(
        "2024 foi um ano importante para todos.",
        font_size=11.0,
        is_bold=True,
    )
    sentence_starting_with_quantity = _make_paragraph(
        "10 dias após o lançamento oficial do sistema",
        font_size=11.0,
        is_bold=True,
    )
    list_block = ReconstructedList(
        ordered=True,
        items=["Primeiro item", "Segundo item"],
        page_number=1,
        bbox=BoundingBox(72.0, 200.0, 300.0, 240.0),
        font_size=14.0,
        font_name="Helvetica-Bold",
        is_bold=True,
        is_italic=False,
    )
    regular_body = _make_paragraph(
        "Parágrafo comum do corpo do documento com fonte padrão de onze pontos "
        "utilizado como referência para o cálculo da mediana tipográfica.",
        font_size=11.0,
        is_bold=False,
    )

    assert evaluate_heading_candidate(bold_sentence_with_period, 11.0) is None
    assert evaluate_heading_candidate(long_bold_large_paragraph, 11.0) is None
    assert evaluate_heading_candidate(sentence_starting_with_year, 11.0) is None
    assert evaluate_heading_candidate(list_block, 11.0) is None

    candidate_same_size = evaluate_heading_candidate(bold_phrase_same_size, 11.0)
    assert candidate_same_size is None or (
        candidate_same_size.confidence < DEFAULT_MIN_HEADING_CONFIDENCE
    )

    candidate_quantity = evaluate_heading_candidate(sentence_starting_with_quantity, 11.0)
    assert candidate_quantity is None or (
        candidate_quantity.confidence < DEFAULT_MIN_HEADING_CONFIDENCE
    )

    all_blocks: list[ReconstructedCandidateBlock] = [
        bold_sentence_with_period,
        bold_phrase_same_size,
        long_bold_large_paragraph,
        sentence_starting_with_year,
        sentence_starting_with_quantity,
        list_block,
        regular_body,
    ]
    assert detect_headings(all_blocks) == []


def test_document_without_reliable_headings_does_not_invent_titles(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sem_titulos.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(
        (72, 100),
        "Primeiro parágrafo contínuo de um documento simples que possui apenas",
        fontname="helv",
        fontsize=11,
    )
    page.insert_text(
        (72, 115),
        "texto corrido em tamanho uniforme sem divisões de capítulos.",
        fontname="helv",
        fontsize=11,
    )
    page.insert_text(
        (72, 160),
        "Segundo parágrafo com um termo destacado mas mantendo a mesma estrutura.",
        fontname="hebo",
        fontsize=11,
    )
    doc.save(str(pdf_path))
    doc.close()

    pages = extract_pdf_pages(pdf_path)
    reconstructed = reconstruct_blocks_from_pages(pages)
    classified = classify_headings(reconstructed)

    assert len(classified) == 2
    assert all(isinstance(b, ReconstructedParagraph) for b in classified)
    assert detect_headings(reconstructed) == []


def _make_column_block(
    text: str,
    x0: float,
    x1: float,
    y0: float,
    *,
    line_count: int = 1,
    font_size: float = 9.5,
    page_number: int = 1,
) -> ReconstructedParagraph:
    return ReconstructedParagraph(
        text=text,
        page_number=page_number,
        bbox=BoundingBox(x0, y0, x1, y0 + 12.8 * line_count),
        font_size=font_size,
        font_name="MinionPro-Regular",
        is_bold=False,
        is_italic=False,
        line_count=line_count,
    )


def _body_text(seed: str) -> str:
    return (
        f"{seed} é um parágrafo longo do corpo do texto que ocupa toda a largura "
        "da coluna e serve para estabelecer a mediana tipográfica do documento."
    )


def test_centered_uppercase_title_split_across_lines_followed_by_date_is_level_one() -> None:
    blocks = [
        _make_column_block(_body_text("Antes"), 36.0, 250.0, 40.0, line_count=12),
        _make_column_block("SOBRE A FRENTE ÚNICA INTERNACIONAL", 50.0, 236.0, 200.0),
        _make_column_block("ANTIFASCISTA*", 108.0, 178.0, 212.0),
        _make_column_block("(23 de Junho de 1941)", 100.0, 186.0, 235.0),
        _make_column_block(_body_text("Depois"), 36.0, 250.0, 260.0, line_count=10),
    ]

    classified = classify_headings(blocks)
    headings = [item for item in classified if isinstance(item, DetectedHeading)]

    assert len(classified) == 4
    assert len(headings) == 1
    assert headings[0].text == "SOBRE A FRENTE ÚNICA INTERNACIONAL ANTIFASCISTA*"
    assert headings[0].level == 1
    assert headings[0].confidence >= DEFAULT_MIN_HEADING_CONFIDENCE


def test_centered_uppercase_subtitle_without_date_is_level_two() -> None:
    blocks = [
        _make_column_block(_body_text("Antes"), 36.0, 250.0, 40.0, line_count=12),
        _make_column_block("A GUERRA POPULAR", 95.0, 191.0, 200.0, font_size=9.0),
        _make_column_block(_body_text("Depois"), 36.0, 250.0, 230.0, line_count=10),
    ]

    headings = detect_headings(blocks)

    assert [(h.text, h.level) for h in headings] == [("A GUERRA POPULAR", 2)]


def test_uppercase_text_that_is_not_centered_is_not_promoted() -> None:
    blocks = [
        _make_column_block(_body_text("Antes"), 36.0, 250.0, 40.0, line_count=12),
        _make_column_block("SIGLA ALINHADA À ESQUERDA", 36.0, 160.0, 200.0),
        _make_column_block(_body_text("Depois"), 36.0, 250.0, 230.0, line_count=10),
    ]

    assert detect_headings(blocks) == []


def test_centered_single_item_uppercase_list_becomes_subtitle_with_marker() -> None:
    blocks: list[ReconstructedCandidateBlock] = [
        _make_column_block(_body_text("Antes"), 36.0, 250.0, 40.0, line_count=12),
        ReconstructedList(
            ordered=True,
            items=["AS REIVINDICAÇÕES FUNDAMENTAIS DO POVO"],
            page_number=1,
            bbox=BoundingBox(45.0, 200.0, 241.0, 224.0),
            font_size=9.5,
            font_name="MinionPro-Regular",
            is_bold=False,
            is_italic=False,
            markers=["I."],
        ),
        _make_column_block(_body_text("Depois"), 36.0, 250.0, 230.0, line_count=10),
    ]

    headings = detect_headings(blocks)

    assert [(h.text, h.level) for h in headings] == [
        ("I. AS REIVINDICAÇÕES FUNDAMENTAIS DO POVO", 2)
    ]


def test_chapter_keyword_detected_when_smaller_than_body_and_long_roman() -> None:
    blocks = [
        _make_column_block(
            _body_text("Parágrafo 1"), 36.0, 450.0, 40.0, font_size=12.0, line_count=10
        ),
        _make_column_block("CAPÍTULO II", 180.0, 300.0, 200.0, font_size=10.0),
        _make_column_block(
            _body_text("Parágrafo 2"), 36.0, 450.0, 230.0, font_size=12.0, line_count=10
        ),
        _make_column_block("CAPÍTULO CXXXVIII", 160.0, 320.0, 400.0, font_size=10.0),
        _make_column_block(
            _body_text("Parágrafo 3"), 36.0, 450.0, 430.0, font_size=12.0, line_count=10
        ),
    ]

    headings = detect_headings(blocks)

    assert [(h.text, h.level) for h in headings] == [
        ("CAPÍTULO II", 1),
        ("CAPÍTULO CXXXVIII", 1),
    ]
