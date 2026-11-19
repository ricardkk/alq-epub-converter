from __future__ import annotations

import os
import re
import shutil
import subprocess
from enum import StrEnum
from pathlib import Path
from typing import Any

from alq.errors import TextExtractionError
from alq.pdf.layout import order_page_blocks
from alq.pdf.text_extractor import (
    BoundingBox,
    ExtractedBlock,
    ExtractedLine,
    ExtractedPage,
    ExtractedSpan,
)
from alq.protocol import emit_debug

ENV_ALQ_TESSERACT_BIN: str = "ALQ_TESSERACT_BIN"
DEFAULT_OCR_DPI: int = 200

_BLANK_LINE_SPLIT_RE = re.compile(r"\n\s*\n+")

_LANGUAGE_MAP: dict[str, str] = {
    "pt": "por",
    "pt-br": "por",
    "pt_br": "por",
    "pt-pt": "por",
    "por": "por",
    "en": "eng",
    "en-us": "eng",
    "en_us": "eng",
    "en-gb": "eng",
    "eng": "eng",
    "es": "spa",
    "es-es": "spa",
    "es-mx": "spa",
    "spa": "spa",
    "fr": "fra",
    "fr-fr": "fra",
    "fra": "fra",
    "de": "deu",
    "de-de": "deu",
    "deu": "deu",
    "it": "ita",
    "it-it": "ita",
    "ita": "ita",
}


class OcrMode(StrEnum):
    NEVER = "never"
    AUTO = "auto"
    ALWAYS = "always"

    @classmethod
    def from_value(cls, value: OcrMode | str | None) -> OcrMode:
        if isinstance(value, OcrMode):
            return value
        if value is None:
            return cls.NEVER
        cleaned = str(value).strip().lower()
        if not cleaned:
            return cls.NEVER
        for member in cls:
            if member.value == cleaned:
                return member
        raise TextExtractionError(
            f"Modo de OCR inválido: '{value}'. Valores suportados: auto, always, never."
        )


def find_tesseract_binary() -> str | None:
    env_override = os.environ.get(ENV_ALQ_TESSERACT_BIN, "").strip()
    if env_override:
        override_path = Path(env_override)
        if override_path.is_file():
            return str(override_path)
        resolved_env = shutil.which(env_override)
        return resolved_env
    return shutil.which("tesseract")


def resolve_tesseract_language(language: str | None) -> str:
    if language is None:
        return "por+eng"
    cleaned = language.strip().lower()
    if not cleaned or cleaned == "und":
        return "por+eng"
    if cleaned in _LANGUAGE_MAP:
        return _LANGUAGE_MAP[cleaned]
    primary = cleaned.split("-", 1)[0].split("_", 1)[0]
    if primary in _LANGUAGE_MAP:
        return _LANGUAGE_MAP[primary]
    return "eng"


def build_extracted_page_from_ocr_text(
    raw_text: str,
    *,
    page_number: int,
    width: float = 595.0,
    height: float = 842.0,
    order_layout: bool = True,
) -> ExtractedPage:
    safe_width = round(float(width if width > 0.0 else 595.0), 2)
    safe_height = round(float(height if height > 0.0 else 842.0), 2)

    cleaned_raw = raw_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned_raw:
        return ExtractedPage(
            page_number=page_number,
            width=safe_width,
            height=safe_height,
            blocks=[],
        )

    raw_chunks = [
        chunk.strip() for chunk in _BLANK_LINE_SPLIT_RE.split(cleaned_raw) if chunk.strip()
    ]

    blocks: list[ExtractedBlock] = []
    current_y = 125.0
    left_x0 = 72.0
    right_x1 = max(200.0, round(safe_width - 72.0, 2))
    default_font_size = 11.0
    default_font_name = "Helvetica"
    line_height = 12.0
    line_step = 14.0
    block_gap = 24.0

    for order_idx, chunk in enumerate(raw_chunks):
        chunk_lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not chunk_lines:
            continue

        extracted_lines: list[ExtractedLine] = []
        for line_str in chunk_lines:
            line_y0 = round(current_y, 2)
            line_y1 = round(line_y0 + line_height, 2)
            est_width = min(right_x1 - left_x0, max(60.0, len(line_str) * 5.8))
            line_x1 = round(left_x0 + est_width, 2)
            line_bbox = BoundingBox(left_x0, line_y0, line_x1, line_y1)
            span = ExtractedSpan(
                text=line_str,
                bbox=line_bbox,
                font_size=default_font_size,
                font_name=default_font_name,
                flags=0,
                is_bold=False,
                is_italic=False,
            )
            extracted_lines.append(
                ExtractedLine(
                    text=line_str,
                    bbox=line_bbox,
                    spans=[span],
                    font_size=default_font_size,
                    font_name=default_font_name,
                    is_bold=False,
                    is_italic=False,
                    flags=0,
                )
            )
            current_y += line_step

        block_bbox = BoundingBox.merge([line.bbox for line in extracted_lines])
        blocks.append(
            ExtractedBlock(
                page_number=page_number,
                text="\n".join(line.text for line in extracted_lines),
                bbox=block_bbox,
                lines=extracted_lines,
                font_size=default_font_size,
                font_name=default_font_name,
                flags=0,
                is_bold=False,
                is_italic=False,
                extraction_order=order_idx,
                column_index=0,
            )
        )
        current_y += block_gap

    if order_layout and blocks:
        blocks = order_page_blocks(blocks, safe_width)

    return ExtractedPage(
        page_number=page_number,
        width=safe_width,
        height=safe_height,
        blocks=blocks,
    )


def _run_tesseract_command(
    tesseract_bin: str,
    png_bytes: bytes,
    tess_lang: str,
    dpi: int,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            tesseract_bin,
            "stdin",
            "stdout",
            "-l",
            tess_lang,
            "--dpi",
            str(dpi),
        ],
        input=png_bytes,
        capture_output=True,
        check=False,
    )


def ocr_pdf_page(
    page: Any,
    page_number: int,
    *,
    language: str = "und",
    dpi: int = DEFAULT_OCR_DPI,
    order_layout: bool = True,
    debug: bool = False,
) -> ExtractedPage:
    tesseract_bin = find_tesseract_binary()
    if tesseract_bin is None:
        raise TextExtractionError(
            f"OCR solicitado para a página {page_number}, mas o executável 'tesseract' "
            "não foi encontrado no sistema.",
            hint=(
                "Instale o Tesseract OCR no sistema (ex.: 'sudo apt install tesseract-ocr "
                "tesseract-ocr-por') ou configure ALQ_TESSERACT_BIN."
            ),
        )

    try:
        rect = page.rect
        page_width = round(float(rect.width), 2)
        page_height = round(float(rect.height), 2)
        pixmap = page.get_pixmap(dpi=dpi, alpha=False)
        png_bytes = bytes(pixmap.tobytes("png"))
    except Exception as exc:
        raise TextExtractionError(
            f"Falha ao renderizar a página {page_number} para execução de OCR: {exc}"
        ) from exc

    tess_lang = resolve_tesseract_language(language)
    emit_debug(
        f"Executando OCR via '{tesseract_bin}' na página {page_number} "
        f"(lang={tess_lang}, dpi={dpi})",
        enabled=debug,
    )

    try:
        proc = _run_tesseract_command(tesseract_bin, png_bytes, tess_lang, dpi)
        if proc.returncode != 0 and tess_lang == "por+eng":
            proc = _run_tesseract_command(tesseract_bin, png_bytes, "eng", dpi)
    except OSError as exc:
        raise TextExtractionError(
            f"Não foi possível iniciar o processo Tesseract OCR ('{tesseract_bin}') "
            f"na página {page_number}: {exc}",
            hint="Verifique se o binário do Tesseract possui permissão de execução.",
        ) from exc

    if proc.returncode != 0:
        stderr_msg = proc.stderr.decode("utf-8", errors="replace").strip()
        raise TextExtractionError(
            f"Falha na execução do Tesseract OCR na página {page_number} "
            f"(código {proc.returncode}): {stderr_msg}",
            hint=(f"Verifique se o pacote de idioma '{tess_lang}' do Tesseract está instalado."),
        )

    recognized_text = proc.stdout.decode("utf-8", errors="replace")
    return build_extracted_page_from_ocr_text(
        recognized_text,
        page_number=page_number,
        width=page_width,
        height=page_height,
        order_layout=order_layout,
    )


__all__ = [
    "DEFAULT_OCR_DPI",
    "ENV_ALQ_TESSERACT_BIN",
    "OcrMode",
    "build_extracted_page_from_ocr_text",
    "find_tesseract_binary",
    "ocr_pdf_page",
    "resolve_tesseract_language",
]
