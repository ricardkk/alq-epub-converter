//! Tipos e desserialização estrita do Contrato JSON v1 (`stdout`) emitido pelo worker Python.

use serde::{Deserialize, Serialize};

use crate::error::{AlqError, Result};

/// Versão suportada do contrato de comunicação JSON entre Rust e Python.
pub const SCHEMA_VERSION: u32 = 1;

/// Status da operação reportado pelo worker Python.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ResponseStatus {
    /// Operação concluída com sucesso.
    Success,
    /// Operação encerrada com erro estruturado.
    Error,
}

/// Metadados básicos extraídos ou inferidos do documento PDF.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct DocumentMetadata {
    /// Título do documento, se disponível.
    #[serde(default)]
    pub title: Option<String>,
    /// Autor do documento, se disponível.
    #[serde(default)]
    pub author: Option<String>,
    /// Código de idioma (ex.: `pt-BR`).
    #[serde(default)]
    pub language: Option<String>,
    /// Número total de páginas do documento.
    #[serde(default)]
    pub page_count: usize,
}

/// Estatísticas do processamento retornadas pelo worker Python.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct ConversionStats {
    /// Quantidade de páginas processadas.
    #[serde(default)]
    pub pages_processed: usize,
    /// Quantidade de capítulos detectados/gerados.
    #[serde(default)]
    pub chapters_detected: usize,
    /// Quantidade de imagens extraídas.
    #[serde(default)]
    pub images_extracted: usize,
    /// Quantidade de parágrafos reconstruídos.
    #[serde(default)]
    pub paragraphs_count: usize,
    /// Quantidade de avisos não fatais emitidos.
    #[serde(default)]
    pub warnings_count: usize,
    /// Duração reportada pelo worker em milissegundos.
    #[serde(default)]
    pub duration_ms: u64,
}

/// Payload de erro estruturado retornado pelo worker Python quando `status == "error"`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProtocolErrorPayload {
    /// Código simbólico do erro (ex.: `ENCRYPTED_PDF`, `NO_TEXT_EXTRACTED`).
    pub code: String,
    /// Mensagem descritiva em português.
    pub message: String,
    /// Dica acionável opcional para o usuário.
    #[serde(default)]
    pub hint: Option<String>,
}

/// Envelope raiz do Contrato JSON v1 emitido no `stdout` do worker Python.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WorkerResponse {
    /// Versão do contrato JSON (`1`).
    pub schema_version: u32,
    /// Status geral da operação (`success` ou `error`).
    pub status: ResponseStatus,
    /// Subcomando executado (`convert` ou `inspect`).
    #[serde(default)]
    pub command: Option<String>,
    /// Caminho do arquivo PDF processado.
    #[serde(default)]
    pub input_path: Option<String>,
    /// Caminho do arquivo EPUB gerado (quando aplicável).
    #[serde(default)]
    pub output_path: Option<String>,
    /// Metadados extraídos do documento.
    #[serde(default)]
    pub metadata: Option<DocumentMetadata>,
    /// Estatísticas de execução.
    #[serde(default)]
    pub stats: Option<ConversionStats>,
    /// Lista de avisos não fatais.
    #[serde(default)]
    pub warnings: Vec<String>,
    /// Detalhes do erro caso `status == "error"`.
    #[serde(default)]
    pub error: Option<ProtocolErrorPayload>,
}

/// Realiza o parsing estrito do payload JSON retornado pelo worker Python no `stdout`.
///
/// # Errors
///
/// - [`AlqError::ProtocolError`] se o JSON estiver vazio, malformado ou com `schema_version` incompatível.
/// - [`AlqError::WorkerError`] se o payload indicar `status: "error"`.
pub fn parse_worker_response(raw_stdout: &str) -> Result<WorkerResponse> {
    let trimmed = raw_stdout.trim();
    if trimmed.is_empty() {
        return Err(AlqError::ProtocolError {
            details: "stdout do worker Python está vazio".to_string(),
        });
    }

    let response: WorkerResponse =
        serde_json::from_str(trimmed).map_err(|err| AlqError::ProtocolError {
            details: format!("JSON inválido no stdout: {err}"),
        })?;

    if response.schema_version != SCHEMA_VERSION {
        return Err(AlqError::ProtocolError {
            details: format!(
                "schema_version incompatível: esperado {}, recebido {}",
                SCHEMA_VERSION, response.schema_version
            ),
        });
    }

    if response.status == ResponseStatus::Error {
        let payload = response.error.unwrap_or_else(|| ProtocolErrorPayload {
            code: "CONVERSION_FAILED".to_string(),
            message: "O worker Python reportou falha sem detalhes adicionais.".to_string(),
            hint: None,
        });
        return Err(AlqError::WorkerError {
            code: payload.code,
            message: payload.message,
            hint: payload.hint,
        });
    }

    Ok(response)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_valid_success_response() {
        let json = r#"{
            "schema_version": 1,
            "status": "success",
            "command": "convert",
            "input_path": "entrada.pdf",
            "output_path": "entrada.epub",
            "metadata": {
                "title": "Livro Teste",
                "author": "Autor",
                "language": "pt-BR",
                "page_count": 10
            },
            "stats": {
                "pages_processed": 10,
                "chapters_detected": 2,
                "images_extracted": 1,
                "paragraphs_count": 45,
                "warnings_count": 0,
                "duration_ms": 12
            },
            "warnings": [],
            "error": null
        }"#;

        let parsed = parse_worker_response(json).expect("deve fazer parse de resposta válida");
        assert_eq!(parsed.schema_version, 1);
        assert_eq!(parsed.status, ResponseStatus::Success);
        assert_eq!(parsed.command.as_deref(), Some("convert"));
        assert_eq!(parsed.output_path.as_deref(), Some("entrada.epub"));
    }

    #[test]
    fn rejects_invalid_schema_version() {
        let json = r#"{"schema_version": 99, "status": "success"}"#;
        let err = parse_worker_response(json).unwrap_err();
        assert_eq!(err.code(), "PROTOCOL_ERROR");
    }

    #[test]
    fn converts_worker_error_status_into_alq_error() {
        let json = r#"{
            "schema_version": 1,
            "status": "error",
            "error": {
                "code": "ENCRYPTED_PDF",
                "message": "O PDF está protegido por senha.",
                "hint": "Remova a senha antes de converter."
            }
        }"#;
        let err = parse_worker_response(json).unwrap_err();
        assert_eq!(err.code(), "ENCRYPTED_PDF");
        assert!(err.to_string().contains("protegido por senha"));
    }
}
