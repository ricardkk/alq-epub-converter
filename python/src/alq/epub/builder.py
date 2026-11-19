from __future__ import annotations

import uuid
from pathlib import Path

from ebooklib import epub

from alq.domain.blocks import ImageBlock
from alq.domain.document import Document, ImageAsset
from alq.epub.chapters import create_chapter_items, sanitize_epub_relative_path
from alq.epub.navigation import configure_navigation
from alq.epub.stylesheet import create_stylesheet_item
from alq.errors import EpubBuildError


def collect_referenced_asset_ids(document: Document) -> set[str]:
    referenced: set[str] = set()
    for chapter in document.chapters:
        for block in chapter.blocks:
            if isinstance(block, ImageBlock) and block.asset_id:
                referenced.add(block.asset_id)
    return referenced


def build_epub(document: Document, output_path: Path | str) -> Path:
    target_path = Path(output_path)

    try:
        book = epub.EpubBook()

        raw_identifier = (document.metadata.identifier or "").strip()
        resolved_identifier = raw_identifier if raw_identifier else f"urn:uuid:{uuid.uuid4()}"
        book.set_identifier(resolved_identifier)

        raw_title = (document.metadata.title or "").strip()
        resolved_title = raw_title if raw_title else (target_path.stem.strip() or "Documento")
        book.set_title(resolved_title)

        raw_lang = (document.metadata.language or "").strip()
        resolved_lang = raw_lang if raw_lang and raw_lang.lower() != "und" else "pt-BR"
        book.set_language(resolved_lang)

        raw_author = (document.metadata.author or "").strip()
        if raw_author:
            book.add_author(raw_author)

        stylesheet = create_stylesheet_item()
        book.add_item(stylesheet)

        referenced_ids = collect_referenced_asset_ids(document)
        referenced_assets: dict[str, ImageAsset] = {}
        for asset_id in sorted(referenced_ids):
            asset = document.assets.get(asset_id)
            if asset is None:
                continue
            referenced_assets[asset_id] = asset
            safe_filename = sanitize_epub_relative_path(asset.filename)
            image_item = epub.EpubItem(
                uid=asset.asset_id,
                file_name=safe_filename,
                media_type=asset.media_type,
                content=asset.data,
            )
            book.add_item(image_item)

        chapter_items = create_chapter_items(
            document.chapters,
            language=resolved_lang,
            stylesheet_item=stylesheet,
            assets=referenced_assets,
        )
        for chapter_item in chapter_items:
            book.add_item(chapter_item)

        configure_navigation(book, chapter_items)

        target_path.parent.mkdir(parents=True, exist_ok=True)
        epub.write_epub(str(target_path), book, {})

        if not target_path.is_file() or target_path.stat().st_size <= 0:
            raise EpubBuildError(
                f"O arquivo EPUB '{target_path}' não foi gravado corretamente em disco."
            )

        return target_path
    except EpubBuildError:
        raise
    except Exception as exc:
        raise EpubBuildError(
            f"Falha ao construir e gravar o arquivo EPUB '{target_path}': {exc}",
            hint=(
                "Verifique permissões de escrita no diretório de destino "
                "e a integridade do conteúdo."
            ),
        ) from exc


__all__ = [
    "build_epub",
    "collect_referenced_asset_ids",
]
