from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from collections.abc import Sequence
from pathlib import Path

from alq.domain.document import Document
from alq.domain.metadata import Metadata
from alq.epub.builder import build_epub
from alq.errors import AlqWorkerError, ErrorCode
from alq.pdf.reader import inspect_pdf
from alq.pdf.text_extractor import extract_pdf_pages
from alq.pipeline import assemble_chapters
from alq.processing.cleanup import filter_headers_and_footers
from alq.processing.headings import classify_headings
from alq.processing.paragraphs import reconstruct_blocks_from_pages
from alq.protocol import (
    SCHEMA_VERSION,
    DocumentMetadataPayload,
    DocumentStatisticsPayload,
    WorkerResponsePayload,
    build_error_response,
    build_error_response_from_exception,
    emit_debug,
    emit_stage,
)

ENV_SIMULATE_ERROR = "ALQ_SIMULATE_ERROR"
ENV_ALQ_DEBUG = "ALQ_DEBUG"
ENV_PDF2EPUB_DEBUG = "PDF2EPUB_DEBUG"


def _is_truthy_env(name: str) -> bool:
    val = os.environ.get(name, "").strip().lower()
    return val in ("1", "true", "yes", "on", "debug")


def is_debug_mode(cli_debug: bool = False) -> bool:
    return cli_debug or _is_truthy_env(ENV_ALQ_DEBUG) or _is_truthy_env(ENV_PDF2EPUB_DEBUG)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alq",
        description="Worker Python de conversão e inspeção de PDF para EPUB.",
    )
    parser.add_argument(
        "--simulate-error",
        dest="simulate_error",
        help=argparse.SUPPRESS,
    )
    subparsers = parser.add_subparsers(dest="command")

    convert_parser = subparsers.add_parser(
        "convert",
        help="Executa o pipeline de conversão de PDF para EPUB.",
    )
    convert_parser.add_argument(
        "input",
        nargs="?",
        help="Caminho do arquivo PDF de entrada.",
    )
    convert_parser.add_argument(
        "--input",
        dest="input_flag",
        help="Caminho do arquivo PDF de entrada (alternativa por flag).",
    )
    convert_parser.add_argument(
        "-o",
        "--output",
        help="Caminho do arquivo EPUB de saída.",
    )
    convert_parser.add_argument(
        "-l",
        "--language",
        help="Código de idioma principal do documento.",
    )
    convert_parser.add_argument(
        "--debug",
        action="store_true",
        help="Ativa logs técnicos de depuração no stderr.",
    )
    convert_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Permite sobrescrever arquivo de saída existente.",
    )
    convert_parser.add_argument(
        "--simulate-error",
        dest="sub_simulate_error",
        help=argparse.SUPPRESS,
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspeciona metadados e estrutura básica de um PDF.",
    )
    inspect_parser.add_argument(
        "input",
        nargs="?",
        help="Caminho do arquivo PDF de entrada.",
    )
    inspect_parser.add_argument(
        "--input",
        dest="input_flag",
        help="Caminho do arquivo PDF de entrada (alternativa por flag).",
    )
    inspect_parser.add_argument(
        "--json",
        action="store_true",
        help="Emite resultado em formato JSON v1 no stdout.",
    )
    inspect_parser.add_argument(
        "--debug",
        action="store_true",
        help="Ativa logs técnicos de depuração no stderr.",
    )
    inspect_parser.add_argument(
        "--simulate-error",
        dest="sub_simulate_error",
        help=argparse.SUPPRESS,
    )

    return parser


def _resolve_simulated_error(parsed: argparse.Namespace) -> str | None:
    flag_val: str | None = getattr(parsed, "sub_simulate_error", None) or getattr(
        parsed, "simulate_error", None
    )
    if flag_val and flag_val.strip():
        return flag_val.strip()
    env_val = os.environ.get(ENV_SIMULATE_ERROR, "").strip()
    return env_val if env_val else None


def _execute_command(parsed: argparse.Namespace) -> int:
    command = parsed.command
    if command not in ("convert", "inspect"):
        return 0

    debug = is_debug_mode(bool(getattr(parsed, "debug", False)))
    raw_input: str | None = getattr(parsed, "input", None) or getattr(parsed, "input_flag", None)
    if not raw_input:
        raise AlqWorkerError(
            ErrorCode.INVALID_INPUT,
            "O caminho do arquivo PDF de entrada é obrigatório.",
        )

    input_path = Path(raw_input)
    emit_debug(f"Comando '{command}' iniciado para '{input_path}'", enabled=debug)

    simulated_code = _resolve_simulated_error(parsed)
    if simulated_code is not None:
        emit_stage(1, 6, "Analisando PDF...")
        raise AlqWorkerError(simulated_code)

    if command == "convert":
        start_ns = time.perf_counter_ns()
        output_str = getattr(parsed, "output", None) or str(input_path.with_suffix(".epub"))
        output_path = Path(output_str)
        language_override: str | None = getattr(parsed, "language", None)

        emit_stage(1, 6, "Analisando PDF...")
        inspection = inspect_pdf(input_path, debug=debug)

        emit_stage(2, 6, "Extraindo conteúdo...")
        extracted_pages = extract_pdf_pages(input_path, order_layout=True, debug=debug)

        emit_stage(3, 6, "Reconstruindo estrutura...")
        cleaned_pages = filter_headers_and_footers(extracted_pages)
        reconstructed_blocks = reconstruct_blocks_from_pages(
            cleaned_pages,
            clean_headers_footers=False,
            merge_across_pages=True,
        )
        classified_blocks = classify_headings(reconstructed_blocks)
        chapters = assemble_chapters(classified_blocks)

        emit_stage(4, 6, "Extraindo imagens...")
        cleaned_override = language_override.strip() if language_override is not None else ""
        resolved_language = cleaned_override if cleaned_override else inspection.language
        doc_metadata = Metadata(
            title=inspection.title,
            author=inspection.author,
            language=resolved_language,
            identifier=inspection.identifier,
        )
        document = Document(
            metadata=doc_metadata,
            chapters=chapters,
            warnings=list(inspection.warnings),
        )

        emit_stage(5, 6, "Gerando EPUB...")
        emit_debug(f"Saída resolvida para '{output_str}'", enabled=debug)
        build_epub(document, output_path)

        emit_stage(6, 6, "Validando arquivo...")

        elapsed_ms = max(0, int((time.perf_counter_ns() - start_ns) / 1_000_000))
        response = WorkerResponsePayload(
            schema_version=SCHEMA_VERSION,
            status="success",
            command="convert",
            input=str(input_path),
            output=output_str,
            metadata=DocumentMetadataPayload(
                title=document.metadata.title,
                author=document.metadata.author,
                language=document.metadata.language,
                identifier=document.metadata.identifier,
            ),
            statistics=DocumentStatisticsPayload(
                pages=inspection.pages,
                pages_with_text=inspection.pages_with_text,
                pages_without_text=inspection.pages_without_text,
                chapters=len(document.chapters),
                paragraphs=document.paragraph_count,
                images=document.image_count,
                page_dimensions=inspection.page_dimensions,
                needs_ocr=inspection.needs_ocr,
            ),
            warnings=list(document.warnings),
            duration_ms=elapsed_ms,
            error=None,
        )
        print(response.to_json(), file=sys.stdout, flush=True)
        return 0

    emit_stage(1, 2, "Abrindo e validando documento PDF")
    inspection = inspect_pdf(input_path, debug=debug)
    emit_stage(2, 2, "Inspeção do PDF concluída")
    response = inspection.to_worker_response(input_display=str(input_path))
    print(response.to_json(), file=sys.stdout, flush=True)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    if not args_list:
        return 0

    try:
        parsed = parser.parse_args(args_list)
    except SystemExit as exc:
        if exc.code in (0, None):
            return 0
        err_resp = build_error_response(
            ErrorCode.INVALID_INPUT,
            f"Argumentos inválidos informados ao worker Python: {' '.join(args_list)}",
        )
        print(err_resp.to_json(), file=sys.stdout, flush=True)
        return 1

    debug = is_debug_mode(bool(getattr(parsed, "debug", False)))

    try:
        return _execute_command(parsed)
    except AlqWorkerError as exc:
        emit_debug(f"AlqWorkerError [{exc.code}]: {exc.message}", enabled=debug)
        err_resp = build_error_response_from_exception(exc)
        print(err_resp.to_json(), file=sys.stdout, flush=True)
        return 1
    except Exception as exc:
        if debug:
            traceback.print_exc(file=sys.stderr)
        err_resp = build_error_response(
            ErrorCode.CONVERSION_FAILED,
            f"Erro inesperado no worker Python: {exc}",
        )
        print(err_resp.to_json(), file=sys.stdout, flush=True)
        return 1
