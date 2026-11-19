from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from alq.errors import AlqWorkerError, ErrorCode

SCHEMA_VERSION: int = 1


@dataclass(frozen=True, slots=True)
class PageDimensionsPayload:
    width: float = 595.0
    height: float = 842.0


@dataclass(frozen=True, slots=True)
class DocumentMetadataPayload:
    title: str | None = None
    author: str | None = None
    language: str | None = None
    identifier: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentStatisticsPayload:
    pages: int = 0
    pages_with_text: int = 0
    pages_without_text: int = 0
    chapters: int = 0
    paragraphs: int = 0
    images: int = 0
    page_dimensions: PageDimensionsPayload | None = field(default_factory=PageDimensionsPayload)
    needs_ocr: bool = False


ConversionStatsPayload = DocumentStatisticsPayload


@dataclass(frozen=True, slots=True)
class ProtocolErrorPayload:
    code: str
    message: str
    hint: str | None = None


@dataclass(frozen=True, slots=True)
class WorkerResponsePayload:
    schema_version: int = SCHEMA_VERSION
    status: Literal["success", "error"] = "success"
    command: str | None = None
    input: str | None = None
    output: str | None = None
    metadata: DocumentMetadataPayload | None = None
    statistics: DocumentStatisticsPayload | None = None
    warnings: list[str] = field(default_factory=list)
    duration_ms: int | None = None
    error: ProtocolErrorPayload | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.status == "error":
            err_dict: dict[str, Any] = {}
            if self.error is not None:
                err_dict = {
                    "code": self.error.code,
                    "message": self.error.message,
                }
                if self.error.hint is not None:
                    err_dict["hint"] = self.error.hint
            return {
                "schema_version": self.schema_version,
                "status": "error",
                "error": err_dict,
                "warnings": list(self.warnings),
            }

        data: dict[str, Any] = {
            "schema_version": self.schema_version,
            "status": "success",
            "input": self.input,
        }
        if self.command is not None:
            data["command"] = self.command
        if self.output is not None:
            data["output"] = self.output
        data["metadata"] = asdict(self.metadata) if self.metadata is not None else None
        data["statistics"] = asdict(self.statistics) if self.statistics is not None else None
        data["warnings"] = list(self.warnings)
        data["duration_ms"] = self.duration_ms if self.duration_ms is not None else 0
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def emit_stage(current: int, total: int, message: str) -> None:
    safe_total = max(1, total)
    safe_current = max(1, min(safe_total, current))
    clean_message = message.strip()
    print(f"STAGE:{safe_current}/{safe_total}:{clean_message}", file=sys.stderr, flush=True)


def emit_debug(message: str, *, enabled: bool = True) -> None:
    if enabled:
        print(f"DEBUG: {message.strip()}", file=sys.stderr, flush=True)


def build_stub_response(
    command: Literal["convert", "inspect"],
    input_path: str,
    output_path: str | None = None,
    language: str | None = None,
) -> WorkerResponsePayload:
    return WorkerResponsePayload(
        schema_version=SCHEMA_VERSION,
        status="success",
        command=command,
        input=input_path,
        output=output_path if command == "convert" else None,
        metadata=DocumentMetadataPayload(
            title="Stub PDF Document",
            author="Unknown",
            language=language or "pt-BR",
            identifier="urn:uuid:00000000-0000-0000-0000-000000000001",
        ),
        statistics=DocumentStatisticsPayload(
            pages=1,
            pages_with_text=1,
            pages_without_text=0,
            chapters=1,
            paragraphs=1,
            images=0,
            page_dimensions=PageDimensionsPayload(width=595.0, height=842.0),
            needs_ocr=False,
        ),
        warnings=[],
        duration_ms=1,
        error=None,
    )


def build_error_response(
    code: ErrorCode | str,
    message: str,
    *,
    warnings: list[str] | None = None,
    hint: str | None = None,
) -> WorkerResponsePayload:
    return WorkerResponsePayload(
        schema_version=SCHEMA_VERSION,
        status="error",
        warnings=list(warnings) if warnings is not None else [],
        error=ProtocolErrorPayload(
            code=str(code),
            message=message,
            hint=hint,
        ),
    )


def build_error_response_from_exception(exc: AlqWorkerError) -> WorkerResponsePayload:
    return build_error_response(
        code=exc.code,
        message=exc.message,
        warnings=exc.warnings,
        hint=exc.hint,
    )
