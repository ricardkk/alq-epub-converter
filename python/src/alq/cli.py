"""Interface de linha de comando do worker Python `alq`."""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path

from alq.errors import AlqWorkerError, ErrorCode
from alq.pdf.reader import inspect_pdf
from alq.protocol import (
    build_error_response,
    build_error_response_from_exception,
    build_stub_response,
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
    """Verifica se o modo de depuração está ativo por flag ou variável de ambiente."""
    return cli_debug or _is_truthy_env(ENV_ALQ_DEBUG) or _is_truthy_env(ENV_PDF2EPUB_DEBUG)


def build_parser() -> argparse.ArgumentParser:
    """Constrói o parser de argumentos da CLI interna do worker Python `alq`."""
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
        emit_stage(1, 2, "Iniciando leitura do documento PDF")
        raise AlqWorkerError(simulated_code)

    if command == "convert":
        output_str = getattr(parsed, "output", None) or str(input_path.with_suffix(".epub"))
        emit_stage(1, 2, "Inspecionando documento PDF")
        emit_stage(2, 2, "Gerando pacote EPUB (stub)")
        emit_debug(f"Saída resolvida para '{output_str}'", enabled=debug)
        response = build_stub_response(
            command="convert",
            input_path=str(input_path),
            output_path=output_str,
            language=getattr(parsed, "language", None),
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
    """Executa o entrypoint da CLI Python do `alq`."""
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
    except Exception as exc:  # pragma: no cover
        if debug:
            traceback.print_exc(file=sys.stderr)
        err_resp = build_error_response(
            ErrorCode.CONVERSION_FAILED,
            f"Erro inesperado no worker Python: {exc}",
        )
        print(err_resp.to_json(), file=sys.stdout, flush=True)
        return 1
