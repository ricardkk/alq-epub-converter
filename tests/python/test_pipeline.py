from __future__ import annotations

import json
from pathlib import Path

import pymupdf

from alq.domain import (
    Chapter,
    Document,
    Heading,
    ImageAsset,
    ImageBlock,
    ListBlock,
    Metadata,
    Paragraph,
)
from alq.pdf.text_extractor import BoundingBox
from alq.pipeline import assemble_chapters, run_document_pipeline
from alq.processing import (
    ClassifiedBlock,
    DetectedHeading,
    ReconstructedList,
    ReconstructedParagraph,
)


def _make_reconstructed_para(text: str, page_number: int = 1) -> ReconstructedParagraph:
    return ReconstructedParagraph(
        text=text,
        page_number=page_number,
        bbox=BoundingBox(72.0, 120.0, 480.0, 135.0),
        font_size=11.0,
        font_name="Helvetica",
        is_bold=False,
        is_italic=False,
    )


def _make_detected_heading(
    text: str,
    level: int = 1,
    page_number: int = 1,
) -> DetectedHeading:
    return DetectedHeading(
        text=text,
        level=level,
        confidence=0.90,
        page_number=page_number,
        font_size=18.0 if level == 1 else 14.0,
        is_bold=True,
    )


def test_assemble_chapters_with_level1_chapters_subheadings_and_preamble() -> None:
    classified: list[ClassifiedBlock] = [
        _make_reconstructed_para("Nota editorial de abertura antes do primeiro capítulo."),
        _make_detected_heading("CAPÍTULO 1: O Início", level=1),
        _make_reconstructed_para("Primeiro parágrafo do capítulo 1."),
        _make_detected_heading("1.1 Contexto Histórico", level=2),
        _make_reconstructed_para("Parágrafo explicando o contexto histórico."),
        _make_detected_heading("1.1.1 Detalhes Técnicos", level=3),
        ReconstructedList(
            ordered=False,
            items=["Item A", "Item B"],
            page_number=1,
            bbox=BoundingBox(72.0, 200.0, 300.0, 230.0),
            font_size=11.0,
            font_name="Helvetica",
            is_bold=False,
            is_italic=False,
        ),
        _make_detected_heading("CAPÍTULO 2: A Evolução", level=1, page_number=2),
        _make_reconstructed_para("Parágrafo inicial do capítulo 2.", page_number=2),
    ]

    chapters = assemble_chapters(classified)
    assert len(chapters) == 3

    preamble = chapters[0]
    assert preamble.title is None
    assert preamble.level == 1
    assert preamble.blocks == [Paragraph("Nota editorial de abertura antes do primeiro capítulo.")]

    ch1 = chapters[1]
    assert ch1.title == "CAPÍTULO 1: O Início"
    assert ch1.level == 1
    assert ch1.blocks == [
        Heading("CAPÍTULO 1: O Início", level=1),
        Paragraph("Primeiro parágrafo do capítulo 1."),
        Heading("1.1 Contexto Histórico", level=2),
        Paragraph("Parágrafo explicando o contexto histórico."),
        Heading("1.1.1 Detalhes Técnicos", level=3),
        ListBlock(ordered=False, items=["Item A", "Item B"]),
    ]

    ch2 = chapters[2]
    assert ch2.title == "CAPÍTULO 2: A Evolução"
    assert ch2.level == 1
    assert ch2.blocks == [
        Heading("CAPÍTULO 2: A Evolução", level=1),
        Paragraph("Parágrafo inicial do capítulo 2."),
    ]


def test_assemble_chapters_fallback_to_single_chapter_without_headings() -> None:
    classified: list[ClassifiedBlock] = [
        _make_reconstructed_para("Primeiro parágrafo do documento sem títulos."),
        _make_reconstructed_para("Segundo parágrafo do documento sem títulos."),
    ]

    chapters = assemble_chapters(classified)
    assert len(chapters) == 1
    assert chapters[0].title is None
    assert chapters[0].level == 1
    assert chapters[0].blocks == [
        Paragraph("Primeiro parágrafo do documento sem títulos."),
        Paragraph("Segundo parágrafo do documento sem títulos."),
    ]


def test_document_json_serialization_and_counters() -> None:
    meta = Metadata()
    assert meta.title is None
    assert meta.author is None
    assert meta.language == "und"
    assert meta.identifier is None

    asset = ImageAsset(
        asset_id="img_001",
        media_type="image/png",
        data=b"\x89PNG\r\n\x1a\n1234",
        filename="images/img_001.png",
        width=120,
        height=80,
        page_number=1,
    )
    chapter = Chapter(
        title="Capítulo Único",
        level=1,
        blocks=[
            Heading("Capítulo Único", level=1),
            Paragraph("Texto do primeiro parágrafo."),
            ImageBlock(asset_id="img_001", alt_text="Figura 1"),
            ListBlock(ordered=True, items=["Passo 1", "Passo 2"]),
        ],
    )
    doc = Document(
        metadata=meta,
        chapters=[chapter],
        warnings=["Aviso de teste"],
        assets={"img_001": asset},
    )

    assert doc.paragraph_count == 1
    assert doc.heading_count == 1
    assert doc.image_count == 1

    raw_json = doc.to_json()
    parsed = json.loads(raw_json)
    assert parsed["metadata"] == {
        "title": None,
        "author": None,
        "language": "und",
        "identifier": None,
    }
    assert parsed["warnings"] == ["Aviso de teste"]
    assert parsed["assets"]["img_001"] == {
        "asset_id": "img_001",
        "media_type": "image/png",
        "filename": "images/img_001.png",
        "width": 120,
        "height": 80,
        "page_number": 1,
        "size_bytes": 12,
    }
    assert len(parsed["chapters"]) == 1
    blocks_data = parsed["chapters"][0]["blocks"]
    assert [b["type"] for b in blocks_data] == ["heading", "paragraph", "image", "list"]


def test_run_document_pipeline_end_to_end_on_real_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "livro_completo.pdf"
    pdf_doc = pymupdf.open()

    page1 = pdf_doc.new_page(width=595, height=842)
    page1.insert_text((72, 35), "Coleção Técnica ALQ", fontname="helv", fontsize=9)
    page1.insert_text((72, 95), "CAPÍTULO 1: Introdução", fontname="hebo", fontsize=18)
    page1.insert_text(
        (72, 140),
        "Este é o primeiro parágrafo do capítulo inicial que descreve",
        fontname="helv",
        fontsize=11,
    )
    page1.insert_text(
        (72, 155),
        "o funcionamento completo do pipeline modular.",
        fontname="helv",
        fontsize=11,
    )
    page1.insert_text((72, 195), "• Primeiro item da lista", fontname="helv", fontsize=11)
    page1.insert_text((72, 212), "• Segundo item da lista", fontname="helv", fontsize=11)
    page1.insert_text((280, 815), "Página 1", fontname="helv", fontsize=9)

    page2 = pdf_doc.new_page(width=595, height=842)
    page2.insert_text((72, 35), "Coleção Técnica ALQ", fontname="helv", fontsize=9)
    page2.insert_text((72, 95), "CAPÍTULO 2: Arquitetura", fontname="hebo", fontsize=18)
    page2.insert_text((72, 140), "2.1 Modelo Intermediário", fontname="hebo", fontsize=14)
    page2.insert_text(
        (72, 175),
        "O modelo intermediário desacopla a leitura do PDF da geração do EPUB.",
        fontname="helv",
        fontsize=11,
    )
    page2.insert_text((280, 815), "Página 2", fontname="helv", fontsize=9)

    pdf_doc.set_metadata({"title": "Manual ALQ", "author": "Equipe ALQ"})
    pdf_doc.save(str(pdf_path))
    pdf_doc.close()

    artifacts = run_document_pipeline(pdf_path, language_override="pt-BR")
    doc = artifacts.document

    assert doc.metadata.title == "Manual ALQ"
    assert doc.metadata.author == "Equipe ALQ"
    assert doc.metadata.language == "pt-BR"
    assert doc.metadata.identifier is None

    assert len(doc.chapters) == 2
    assert doc.chapters[0].title == "CAPÍTULO 1: Introdução"
    assert doc.chapters[0].blocks == [
        Heading("CAPÍTULO 1: Introdução", level=1),
        Paragraph(
            "Este é o primeiro parágrafo do capítulo inicial que descreve "
            "o funcionamento completo do pipeline modular."
        ),
        ListBlock(
            ordered=False,
            items=["Primeiro item da lista", "Segundo item da lista"],
        ),
    ]

    assert doc.chapters[1].title == "CAPÍTULO 2: Arquitetura"
    assert doc.chapters[1].blocks == [
        Heading("CAPÍTULO 2: Arquitetura", level=1),
        Heading("2.1 Modelo Intermediário", level=2),
        Paragraph("O modelo intermediário desacopla a leitura do PDF da geração do EPUB."),
    ]

    artifacts_dict = artifacts.to_dict()
    assert set(artifacts_dict.keys()) == {
        "extracted_pages",
        "cleaned_pages",
        "reconstructed_blocks",
        "classified_blocks",
        "image_extraction",
        "document",
    }


def test_assemble_chapters_absorbs_consecutive_titles_on_same_page() -> None:
    classified: list[ClassifiedBlock] = [
        _make_detected_heading("OBRAS ESCOLHIDAS DE", level=1, page_number=1),
        _make_detected_heading("MAO TSETUNG", level=1, page_number=1),
        _make_reconstructed_para("Tomo III", page_number=1),
        _make_detected_heading("PREFÁCIO", level=1, page_number=2),
        _make_reconstructed_para("Texto do prefácio.", page_number=2),
    ]

    chapters = assemble_chapters(classified)

    assert [chapter.title for chapter in chapters] == ["OBRAS ESCOLHIDAS DE", "PREFÁCIO"]
    assert chapters[0].blocks == [
        Heading("OBRAS ESCOLHIDAS DE", level=1),
        Heading("MAO TSETUNG", level=1),
        Paragraph("Tomo III"),
    ]


def test_assemble_chapters_splits_on_deeper_level_when_single_cover_title() -> None:
    classified: list[ClassifiedBlock] = [
        _make_detected_heading("The Metamorphosis", level=1, page_number=1),
        _make_reconstructed_para("Franz Kafka", page_number=1),
        _make_reconstructed_para("Translator note.", page_number=2),
        _make_detected_heading("I", level=3, page_number=3),
        _make_reconstructed_para("One morning, as Gregor Samsa...", page_number=3),
        _make_detected_heading("II", level=3, page_number=33),
        _make_reconstructed_para("Gregor first woke up...", page_number=33),
        _make_detected_heading("III", level=3, page_number=66),
        _make_reconstructed_para("Gregor's serious wound...", page_number=66),
    ]

    chapters = assemble_chapters(classified)

    assert [chapter.title for chapter in chapters] == [
        "The Metamorphosis",
        "I",
        "II",
        "III",
    ]
    assert chapters[0].blocks == [
        Heading("The Metamorphosis", level=1),
        Paragraph("Franz Kafka"),
        Paragraph("Translator note."),
    ]
    assert chapters[1].blocks == [
        Heading("I", level=3),
        Paragraph("One morning, as Gregor Samsa..."),
    ]
