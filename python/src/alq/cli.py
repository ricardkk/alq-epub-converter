"""Interface de linha de comando do worker Python `alq`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from alq.protocol import build_stub_response, emit_stage


def build_parser() -> argparse.ArgumentParser:
    """Constrói o parser de argumentos da CLI interna do worker Python `alq`."""
    parser = argparse.ArgumentParser(
        prog="alq",
        description="Worker Python de conversão e inspeção de PDF para EPUB.",
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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Executa o entrypoint da CLI Python do `alq`."""
    args_list = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    if not args_list:
        return 0

    parsed = parser.parse_args(args_list)
    command = parsed.command
    if command not in ("convert", "inspect"):
        return 0

    raw_input: str | None = parsed.input or parsed.input_flag
    if not raw_input:
        parser.error("argumento INPUT é obrigatório")

    input_path = Path(raw_input)

    if command == "convert":
        output_str = parsed.output or str(input_path.with_suffix(".epub"))
        if parsed.debug:
            emit_stage("convert", 100, "Execução stub de conversão concluída")
        response = build_stub_response(
            command="convert",
            input_path=str(input_path),
            output_path=output_str,
            language=parsed.language,
        )
        print(response.to_json(), file=sys.stdout, flush=True)
        return 0

    if parsed.debug:
        emit_stage("inspect", 100, "Execução stub de inspeção concluída")
    response = build_stub_response(
        command="inspect",
        input_path=str(input_path),
        output_path=None,
        language=None,
    )
    print(response.to_json(), file=sys.stdout, flush=True)
    return 0
