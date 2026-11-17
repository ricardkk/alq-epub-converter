"""Definição e serialização do Contrato JSON v1 (`stdout`) e eventos de progresso (`stderr`)."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Literal

SCHEMA_VERSION: int = 1


@dataclass(frozen=True, slots=True)
class DocumentMetadataPayload:
    """Metadados básicos do documento no Contrato JSON v1."""

    title: str | None = None
    author: str | None = None
    language: str | None = None
    page_count: int = 0


@dataclass(frozen=True, slots=True)
class ConversionStatsPayload:
    """Estatísticas de execução do pipeline no Contrato JSON v1."""

    pages_processed: int = 0
    chapters_detected: int = 0
    images_extracted: int = 0
    paragraphs_count: int = 0
    warnings_count: int = 0
    duration_ms: int = 0


@dataclass(frozen=True, slots=True)
class ProtocolErrorPayload:
    """Payload de erro estruturado no Contrato JSON v1."""

    code: str
    message: str
    hint: str | None = None


@dataclass(frozen=True, slots=True)
class WorkerResponsePayload:
    """Envelope raiz do Contrato JSON v1 emitido no `stdout`."""

    schema_version: int = SCHEMA_VERSION
    status: Literal["success", "error"] = "success"
    command: str | None = None
    input_path: str | None = None
    output_path: str | None = None
    metadata: DocumentMetadataPayload | None = None
    stats: ConversionStatsPayload | None = None
    warnings: list[str] = field(default_factory=list)
    error: ProtocolErrorPayload | None = None

    def to_json(self) -> str:
        """Serializa a resposta para uma string JSON compacta em linha única."""
        return json.dumps(asdict(self), ensure_ascii=False)


def emit_stage(stage: str, percent: int, message: str) -> None:
    """Emite evento estruturado de progresso exclusivamente no `stderr`."""
    clamped = max(0, min(100, percent))
    print(f"STAGE:{stage}:{clamped}:{message}", file=sys.stderr, flush=True)


def build_stub_response(
    command: Literal["convert", "inspect"],
    input_path: str,
    output_path: str | None = None,
    language: str | None = None,
) -> WorkerResponsePayload:
    """Constrói uma resposta simulada válida do Contrato JSON v1 para testes de integração."""
    return WorkerResponsePayload(
        schema_version=SCHEMA_VERSION,
        status="success",
        command=command,
        input_path=input_path,
        output_path=output_path,
        metadata=DocumentMetadataPayload(
            title="Stub PDF Document",
            author="Unknown",
            language=language or "pt-BR",
            page_count=1,
        ),
        stats=ConversionStatsPayload(
            pages_processed=1,
            chapters_detected=1,
            images_extracted=0,
            paragraphs_count=1,
            warnings_count=0,
            duration_ms=1,
        ),
        warnings=[],
        error=None,
    )
