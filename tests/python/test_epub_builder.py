from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

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
from alq.epub import (
    DEFAULT_CSS,
    DEFAULT_STYLESHEET_PATH,
    build_epub,
    render_block_xhtml,
    render_chapter_body_xhtml,
    sanitize_epub_relative_path,
)


def test_html_escaping_in_paragraphs_headings_lists_and_images() -> None:
    para = Paragraph("Texto com <script>alert(\"xss\")</script> & 'aspas'.")
    rendered_para = render_block_xhtml(para)
    assert "<script>" not in rendered_para
    assert "&lt;script&gt;" in rendered_para
    assert "&amp;" in rendered_para
    assert "&quot;xss&quot;" in rendered_para
    assert "'aspas'" not in rendered_para
    assert "x27;aspas" in rendered_para

    heading = Heading("Título <1> & Subtítulo", level=9)
    rendered_heading = render_block_xhtml(heading)
    assert rendered_heading == "<h6>Título &lt;1&gt; &amp; Subtítulo</h6>"

    lst = ListBlock(ordered=True, items=["Item <b>1</b>", "Item & 2"])
    rendered_list = render_block_xhtml(lst)
    assert rendered_list == "<ol><li>Item &lt;b&gt;1&lt;/b&gt;</li><li>Item &amp; 2</li></ol>"

    asset = ImageAsset(
        asset_id="img_001",
        media_type="image/png",
        data=b"\x89PNG\r\n\x1a\n",
        filename="../../../etc/img_001.png",
    )
    img_block = ImageBlock(asset_id="img_001", alt_text='Legenda "segura" & <limpa>')
    rendered_img = render_block_xhtml(img_block, {"img_001": asset})
    assert 'src="etc/img_001.png"' in rendered_img
    assert 'alt="Legenda &quot;segura&quot; &amp; &lt;limpa&gt;"' in rendered_img

    assert sanitize_epub_relative_path("/absoluto/../../img_001.png") == "absoluto/img_001.png"
    assert sanitize_epub_relative_path("img_001.png") == "images/img_001.png"


def test_render_chapter_body_xhtml_handles_empty_chapter_validly() -> None:
    empty_chapter = Chapter(title=None, level=1, blocks=[])
    xhtml = render_chapter_body_xhtml(empty_chapter)
    parsed = ET.fromstring(xhtml)
    assert parsed.tag == "section"


def test_build_epub_creates_valid_epub3_package_and_excludes_unreferenced_assets(
    tmp_path: Path,
) -> None:
    used_asset = ImageAsset(
        asset_id="img_001",
        media_type="image/png",
        data=b"\x89PNG\r\n\x1a\nfake_png_data",
        filename="images/img_001.png",
        width=100,
        height=100,
        page_number=1,
    )
    unused_asset = ImageAsset(
        asset_id="img_unused",
        media_type="image/png",
        data=b"\x89PNG\r\n\x1a\nunused_data",
        filename="images/unused.png",
        width=50,
        height=50,
        page_number=2,
    )

    doc = Document(
        metadata=Metadata(
            title="Arquitetura EPUB & Conversão",
            author="Autora Principal",
            language="pt-BR",
            identifier="urn:uuid:11111111-2222-3333-4444-555555555555",
        ),
        chapters=[
            Chapter(
                title="Capítulo 1: Fundamentos & Estrutura",
                level=1,
                blocks=[
                    Heading("Capítulo 1: Fundamentos & Estrutura", level=1),
                    Paragraph("Primeiro parágrafo com caracteres <especiais> & acentuação."),
                    Heading("1.1 Elementos Visuais", level=2),
                    ImageBlock(asset_id="img_001", alt_text="Diagrama 1"),
                ],
            ),
            Chapter(
                title="Capítulo 2: Listas",
                level=1,
                blocks=[
                    Heading("Capítulo 2: Listas", level=1),
                    ListBlock(ordered=False, items=["Ponto A", "Ponto B & C"]),
                    ListBlock(ordered=True, items=["Etapa 1", "Etapa 2"]),
                ],
            ),
        ],
        warnings=[],
        assets={
            "img_001": used_asset,
            "img_unused": unused_asset,
        },
    )

    output_epub = tmp_path / "saida" / "livro.epub"
    built_path = build_epub(doc, output_epub)
    assert built_path == output_epub
    assert output_epub.is_file()
    assert output_epub.stat().st_size > 0

    with zipfile.ZipFile(output_epub, "r") as zf:
        names = set(zf.namelist())
        assert "mimetype" in names
        assert zf.read("mimetype").decode("ascii").strip() == "application/epub+zip"
        assert "META-INF/container.xml" in names
        assert f"EPUB/{DEFAULT_STYLESHEET_PATH}" in names
        assert "EPUB/chapter_001.xhtml" in names
        assert "EPUB/chapter_002.xhtml" in names
        assert "EPUB/nav.xhtml" in names
        assert "EPUB/toc.ncx" in names
        assert "EPUB/images/img_001.png" in names
        assert "EPUB/images/unused.png" not in names

        css_text = zf.read(f"EPUB/{DEFAULT_STYLESHEET_PATH}").decode("utf-8")
        assert DEFAULT_CSS.strip() in css_text

        container_xml = zf.read("META-INF/container.xml").decode("utf-8")
        ET.fromstring(container_xml)

        for ch_name in ("EPUB/chapter_001.xhtml", "EPUB/chapter_002.xhtml"):
            ch_bytes = zf.read(ch_name)
            ET.fromstring(ch_bytes.decode("utf-8"))

        ch1_str = zf.read("EPUB/chapter_001.xhtml").decode("utf-8")
        assert "&lt;especiais&gt;" in ch1_str
        assert 'src="images/img_001.png"' in ch1_str


def test_build_epub_with_minimal_missing_metadata(tmp_path: Path) -> None:
    doc = Document(
        metadata=Metadata(title=None, author=None, language="und", identifier=None),
        chapters=[
            Chapter(
                title=None,
                level=1,
                blocks=[Paragraph("Conteúdo sem metadados explícitos.")],
            )
        ],
    )
    output_epub = tmp_path / "minimal.epub"
    build_epub(doc, output_epub)

    with zipfile.ZipFile(output_epub, "r") as zf:
        opf_content = zf.read("EPUB/content.opf").decode("utf-8")
        ET.fromstring(opf_content)
        assert "minimal" in opf_content
        assert "urn:uuid:" in opf_content
