"""Hierarquia de exceções estruturadas e códigos de erro do pipeline Python `alq`."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """Códigos padronizados de erro do domínio `alq` no Contrato JSON v1."""

    INPUT_NOT_FOUND = "INPUT_NOT_FOUND"
    INVALID_INPUT = "INVALID_INPUT"
    OUTPUT_EXISTS = "OUTPUT_EXISTS"
    PDF_OPEN_FAILED = "PDF_OPEN_FAILED"
    PDF_PASSWORD_REQUIRED = "PDF_PASSWORD_REQUIRED"
    NO_EXTRACTABLE_TEXT = "NO_EXTRACTABLE_TEXT"
    TEXT_EXTRACTION_FAILED = "TEXT_EXTRACTION_FAILED"
    EPUB_BUILD_FAILED = "EPUB_BUILD_FAILED"
    EPUB_VALIDATION_FAILED = "EPUB_VALIDATION_FAILED"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    CONVERSION_FAILED = "CONVERSION_FAILED"


_DEFAULT_MESSAGES: dict[str, str] = {
    ErrorCode.INPUT_NOT_FOUND: "O arquivo de entrada especificado não foi encontrado.",
    ErrorCode.INVALID_INPUT: "O arquivo de entrada informado é inválido.",
    ErrorCode.OUTPUT_EXISTS: "O arquivo de saída já existe e a sobrescrita não foi autorizada.",
    ErrorCode.PDF_OPEN_FAILED: "Não foi possível abrir ou ler o arquivo PDF informado.",
    ErrorCode.PDF_PASSWORD_REQUIRED: (
        "O arquivo PDF está protegido por senha e não pode ser processado."
    ),
    ErrorCode.NO_EXTRACTABLE_TEXT: (
        "Nenhum texto extraível foi encontrado no PDF (possível documento digitalizado sem OCR)."
    ),
    ErrorCode.TEXT_EXTRACTION_FAILED: (
        "Falha durante a extração de texto das páginas do documento PDF."
    ),
    ErrorCode.EPUB_BUILD_FAILED: "Falha ao construir e empacotar o arquivo EPUB de saída.",
    ErrorCode.EPUB_VALIDATION_FAILED: (
        "O pacote EPUB gerado falhou na validação estrutural obrigatória."
    ),
    ErrorCode.PROTOCOL_ERROR: "Violação do protocolo de comunicação JSON v1.",
    ErrorCode.CONVERSION_FAILED: "Ocorreu um erro durante o pipeline de conversão do documento.",
}


def default_error_message(code: ErrorCode | str) -> str:
    """Retorna a mensagem descritiva padrão em português para um dado código de erro."""
    return _DEFAULT_MESSAGES.get(str(code), _DEFAULT_MESSAGES[ErrorCode.CONVERSION_FAILED])


class AlqWorkerError(Exception):
    """Exceção base estruturada do worker Python `alq`."""

    def __init__(
        self,
        code: ErrorCode | str,
        message: str | None = None,
        *,
        hint: str | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        resolved_code = str(code).strip() or str(ErrorCode.CONVERSION_FAILED)
        resolved_message = (message or "").strip() or default_error_message(resolved_code)
        super().__init__(resolved_message)
        self.code: str = resolved_code
        self.message: str = resolved_message
        self.hint: str | None = hint
        self.warnings: list[str] = list(warnings) if warnings is not None else []


class PdfOpenError(AlqWorkerError):
    """Erro ao abrir ou analisar a estrutura inicial de um PDF."""

    def __init__(
        self,
        message: str | None = None,
        *,
        hint: str | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        super().__init__(
            ErrorCode.PDF_OPEN_FAILED,
            message,
            hint=hint,
            warnings=warnings,
        )


class PdfPasswordRequiredError(AlqWorkerError):
    """Erro quando o documento PDF exige senha para leitura."""

    def __init__(
        self,
        message: str | None = None,
        *,
        hint: str | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        super().__init__(
            ErrorCode.PDF_PASSWORD_REQUIRED,
            message,
            hint=hint,
            warnings=warnings,
        )


class NoExtractableTextError(AlqWorkerError):
    """Erro quando nenhuma página do PDF contém texto extraível."""

    def __init__(
        self,
        message: str | None = None,
        *,
        hint: str | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        super().__init__(
            ErrorCode.NO_EXTRACTABLE_TEXT,
            message,
            hint=hint,
            warnings=warnings,
        )


class TextExtractionError(AlqWorkerError):
    """Erro durante a extração de blocos de texto de uma página do PDF."""

    def __init__(
        self,
        message: str | None = None,
        *,
        hint: str | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        super().__init__(
            ErrorCode.TEXT_EXTRACTION_FAILED,
            message,
            hint=hint,
            warnings=warnings,
        )


class EpubBuildError(AlqWorkerError):
    """Erro durante a geração do pacote EPUB."""

    def __init__(
        self,
        message: str | None = None,
        *,
        hint: str | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        super().__init__(
            ErrorCode.EPUB_BUILD_FAILED,
            message,
            hint=hint,
            warnings=warnings,
        )


class EpubValidationError(AlqWorkerError):
    """Erro durante a validação estrutural do pacote EPUB."""

    def __init__(
        self,
        message: str | None = None,
        *,
        hint: str | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        super().__init__(
            ErrorCode.EPUB_VALIDATION_FAILED,
            message,
            hint=hint,
            warnings=warnings,
        )
