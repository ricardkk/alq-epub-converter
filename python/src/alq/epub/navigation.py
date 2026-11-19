from __future__ import annotations

from collections.abc import Sequence

from ebooklib import epub


def configure_navigation(
    book: epub.EpubBook,
    chapter_items: Sequence[epub.EpubHtml],
) -> None:
    toc_links = [epub.Link(item.file_name, item.title, item.id) for item in chapter_items]
    book.toc = tuple(toc_links)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *chapter_items]


__all__ = ["configure_navigation"]
