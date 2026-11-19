from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath

from ebooklib import epub

from alq.domain.blocks import Block, Heading, ImageBlock, ListBlock, Paragraph
from alq.domain.document import Chapter, ImageAsset


def sanitize_epub_relative_path(raw_path: str, *, default_dir: str = "images") -> str:
    normalized = raw_path.replace("\\", "/").strip()
    parts = [part for part in PurePosixPath(normalized).parts if part not in ("", ".", "..", "/")]
    if not parts:
        return f"{default_dir}/asset.bin"
    if len(parts) == 1:
        return f"{default_dir}/{parts[0]}"
    return "/".join(parts)


def chapter_filename(index: int) -> str:
    safe_idx = max(1, int(index))
    return f"chapter_{safe_idx:03d}.xhtml"


def chapter_uid(index: int) -> str:
    safe_idx = max(1, int(index))
    return f"chapter_{safe_idx:03d}"


def resolve_chapter_title(chapter: Chapter, index: int) -> str:
    cleaned = (chapter.title or "").strip()
    return cleaned if cleaned else f"Seção {max(1, int(index))}"


def render_block_xhtml(
    block: Block,
    assets: Mapping[str, ImageAsset] | None = None,
) -> str:
    if isinstance(block, Paragraph):
        escaped_text = html.escape(block.text, quote=True)
        return f"<p>{escaped_text}</p>"

    if isinstance(block, Heading):
        safe_level = max(1, min(6, int(block.level)))
        escaped_text = html.escape(block.text, quote=True)
        return f"<h{safe_level}>{escaped_text}</h{safe_level}>"

    if isinstance(block, ListBlock):
        tag = "ol" if block.ordered else "ul"
        items_markup = "".join(f"<li>{html.escape(item, quote=True)}</li>" for item in block.items)
        return f"<{tag}>{items_markup}</{tag}>"

    if isinstance(block, ImageBlock):
        if assets is None or block.asset_id not in assets:
            return ""
        asset = assets[block.asset_id]
        safe_src = html.escape(sanitize_epub_relative_path(asset.filename), quote=True)
        safe_alt = html.escape(block.alt_text or "", quote=True)
        return f'<figure class="image-block"><img src="{safe_src}" alt="{safe_alt}" /></figure>'

    raise TypeError(f"Unsupported block type: {type(block)!r}")


def render_chapter_body_xhtml(
    chapter: Chapter,
    assets: Mapping[str, ImageAsset] | None = None,
) -> str:
    rendered_blocks = [
        markup for block in chapter.blocks if (markup := render_block_xhtml(block, assets))
    ]
    if not rendered_blocks:
        if chapter.title and chapter.title.strip():
            escaped_title = html.escape(chapter.title.strip(), quote=True)
            rendered_blocks.append(f"<h1>{escaped_title}</h1>")
        else:
            rendered_blocks.append("<p>\u00a0</p>")

    inner_html = "\n".join(rendered_blocks)
    return f'<section class="chapter">\n{inner_html}\n</section>'


def create_chapter_items(
    chapters: Sequence[Chapter],
    *,
    language: str = "pt-BR",
    stylesheet_item: epub.EpubItem | None = None,
    assets: Mapping[str, ImageAsset] | None = None,
) -> list[epub.EpubHtml]:
    effective_chapters = list(chapters) if chapters else [Chapter(title=None, level=1, blocks=[])]
    items: list[epub.EpubHtml] = []

    for idx, chapter in enumerate(effective_chapters, start=1):
        uid = chapter_uid(idx)
        file_name = chapter_filename(idx)
        title = resolve_chapter_title(chapter, idx)
        body_xhtml = render_chapter_body_xhtml(chapter, assets)

        html_item = epub.EpubHtml(
            uid=uid,
            title=title,
            file_name=file_name,
            lang=language,
        )
        html_item.set_content(body_xhtml.encode("utf-8"))
        if stylesheet_item is not None:
            html_item.add_item(stylesheet_item)
        items.append(html_item)

    return items


__all__ = [
    "chapter_filename",
    "chapter_uid",
    "create_chapter_items",
    "render_block_xhtml",
    "render_chapter_body_xhtml",
    "resolve_chapter_title",
    "sanitize_epub_relative_path",
]
