from __future__ import annotations

from ebooklib import epub

DEFAULT_STYLESHEET_PATH: str = "styles/main.css"
DEFAULT_STYLESHEET_ID: str = "style_main"

DEFAULT_CSS: str = "\n".join(
    [
        "body {",
        "    line-height: 1.6;",
        "    margin: 5%;",
        "    text-align: justify;",
        "}",
        "p {",
        "    margin: 0 0 1em 0;",
        "    text-indent: 1.5em;",
        "}",
        "h1, h2, h3, h4, h5, h6 {",
        "    line-height: 1.25;",
        "    margin: 1.5em 0 0.75em 0;",
        "    text-align: left;",
        "    text-indent: 0;",
        "}",
        "img {",
        "    display: block;",
        "    height: auto;",
        "    margin: 1em auto;",
        "    max-width: 100%;",
        "}",
        "figure.image-block {",
        "    margin: 1.2em auto;",
        "    text-align: center;",
        "    text-indent: 0;",
        "}",
        "ul, ol {",
        "    margin: 0.75em 0 1em 2em;",
        "    padding: 0;",
        "}",
        "li {",
        "    margin: 0.25em 0;",
        "}",
        "",
    ]
)


def create_stylesheet_item(css_content: str = DEFAULT_CSS) -> epub.EpubItem:
    return epub.EpubItem(
        uid=DEFAULT_STYLESHEET_ID,
        file_name=DEFAULT_STYLESHEET_PATH,
        media_type="text/css",
        content=css_content.encode("utf-8"),
    )


__all__ = [
    "DEFAULT_CSS",
    "DEFAULT_STYLESHEET_ID",
    "DEFAULT_STYLESHEET_PATH",
    "create_stylesheet_item",
]
