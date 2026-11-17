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

/// Dimensões representativas das páginas do documento PDF (em pontos tipográficos).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PageDimensions {
    /// Largura da página em pontos (`pt`).
    pub width: f64,
    /// Altura da página em pontos (`pt`).
    pub height: f64,
}

impl Default for PageDimensions {
    fn default() -> Self {
        Self {
            width: 595.0,
            height: 842.0,
        }
    }
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
    /// Identificador único do documento (ex.: UUID, ISBN ou URI), se disponível.
    #[serde(default)]
    pub identifier: Option<String>,
}

/// Estatísticas do documento e do processamento retornadas pelo worker Python.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct DocumentStatistics {
    /// Quantidade total de páginas do PDF.
    #[serde(default)]
    pub pages: usize,
    /// Quantidade de páginas com camada de texto extraível.
    #[serde(default)]
    pub pages_with_text: usize,
    /// Quantidade de páginas sem texto extraível.
    #[serde(default)]
    pub pages_without_text: usize,
    /// Quantidade de capítulos detectados/gerados.
    #[serde(default)]
    pub chapters: usize,
    /// Quantidade de parágrafos reconstruídos.
    #[serde(default)]
    pub paragraphs: usize,
    /// Quantidade de imagens extraídas.
    #[serde(default)]
    pub images: usize,
    /// Dimensões representativas das páginas (`width`, `height`).
    #[serde(default)]
    pub page_dimensions: Option<PageDimensions>,
    /// Indica se o documento aparenta exigir OCR (ex.: digitalizado sem texto).
    #[serde(default)]
    pub needs_ocr: bool,
}

/// Alias de compatibilidade para estatísticas de conversão.
pub type ConversionStats = DocumentStatistics;

/// Payload de erro estruturado retornado pelo worker Python quando `status == "error"`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProtocolErrorPayload {
    /// Código simbólico do erro (ex.: `PDF_OPEN_FAILED`, `PDF_PASSWORD_REQUIRED`).
    pub code: String,
    /// Mensagem descritiva em português.
    pub message: String,
    /// Dica acionável opcional para o usuário.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub hint: Option<String>,
}

/// Envelope raiz do Contrato JSON v1 emitido no `stdout` do worker Python.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WorkerResponse {
    /// Versão do contrato JSON (`1`).
    pub schema_version: u32,
    /// Status geral da operação (`success` ou `error`).
    pub status: ResponseStatus,
    /// Subcomando executado (`convert` ou `inspect`), quando informado.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub command: Option<String>,
    /// Caminho do arquivo PDF processado.
    #[serde(default, alias = "input_path", skip_serializing_if = "Option::is_none")]
    pub input: Option<String>,
    /// Caminho do arquivo EPUB gerado (opcional em `inspect`).
    #[serde(
        default,
        alias = "output_path",
        skip_serializing_if = "Option::is_none"
    )]
    pub output: Option<String>,
    /// Metadados extraídos do documento.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub metadata: Option<DocumentMetadata>,
    /// Estatísticas do documento e da execução.
    #[serde(default, alias = "stats", skip_serializing_if = "Option::is_none")]
    pub statistics: Option<DocumentStatistics>,
    /// Lista de avisos não fatais.
    #[serde(default)]
    pub warnings: Vec<String>,
    /// Duração total reportada pelo worker em milissegundos.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub duration_ms: Option<u64>,
    /// Detalhes do erro caso `status == "error"`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<ProtocolErrorPayload>,
}

/// Realiza o parsing estrito do payload JSON retornado pelo worker Python no `stdout`.
///
/// # Errors
///
/// - [`AlqError::ProtocolError`] se o JSON estiver vazio, malformado, com `schema_version` incompatível
///   ou com `status == "error"` desacompanhado de um objeto `error` válido.
/// - Variantes de domínio de [`AlqError`] (ex.: [`AlqError::PdfOpenFailed`], [`AlqError::PdfPasswordRequired`])
///   se o payload indicar `status: "error"` com `error` estruturado.
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

    match response.status {
        ResponseStatus::Error => {
            let Some(payload) = response.error else {
                return Err(AlqError::ProtocolError {
                    details: "status 'error' recebido sem objeto 'error' estruturado".to_string(),
                });
            };

            if payload.code.trim().is_empty() || payload.message.trim().is_empty() {
                return Err(AlqError::ProtocolError {
                    details: "objeto 'error' inválido: campos 'code' e 'message' são obrigatórios"
                        .to_string(),
                });
            }

            Err(AlqError::from_worker_payload(
                payload.code,
                payload.message,
                payload.hint,
            ))
        }
        ResponseStatus::Success => {
            if response.error.is_some() {
                return Err(AlqError::ProtocolError {
                    details: "status 'success' não pode conter objeto 'error'".to_string(),
                });
            }
            Ok(response)
        }
    }
}

/// Avalia de forma combinada o código de saída do processo Python (`exit_code`), o `stdout` e o `stderr`.
///
/// Regras aplicadas:
/// - `exit_code == Some(0)` e `status == "success"` -> `Ok(WorkerResponse)`
/// - `status == "error"` com `error` estruturado válido -> erro de domínio mapeado (`AlqError`)
/// - `exit_code == Some(0)` mas `status == "error"` sem payload de erro válido -> `AlqError::ProtocolError`
/// - `exit_code != Some(0)` mas `status == "success"` -> `AlqError::ProtocolError`
/// - `stdout` vazio e `exit_code == Some(0)` -> `AlqError::ProtocolError`
/// - `stdout` vazio e `exit_code != Some(0)` -> `AlqError::PythonExecutionFailed`
/// - JSON malformado ou `schema_version != 1` -> `AlqError::ProtocolError`
///
/// # Errors
///
/// Retorna [`AlqError`] conforme a tabela de decisão do protocolo.
pub fn evaluate_worker_output(
    exit_code: Option<i32>,
    raw_stdout: &str,
    raw_stderr: &str,
) -> Result<WorkerResponse> {
    let trimmed_stdout = raw_stdout.trim();

    if trimmed_stdout.is_empty() {
        if exit_code == Some(0) {
            return Err(AlqError::ProtocolError {
                details: "stdout do worker Python está vazio mesmo com código de saída 0"
                    .to_string(),
            });
        }

        let status_desc = exit_code.map_or_else(
            || "encerrado por sinal".to_string(),
            |code| format!("código {code}"),
        );
        let trimmed_stderr = raw_stderr.trim();
        let details = if trimmed_stderr.is_empty() {
            format!("processo Python abortou sem emitir JSON ({status_desc})")
        } else {
            format!("processo Python abortou sem emitir JSON ({status_desc}): {trimmed_stderr}")
        };
        return Err(AlqError::PythonExecutionFailed { details });
    }

    let response = parse_worker_response(trimmed_stdout)?;

    if exit_code != Some(0) {
        let code_desc =
            exit_code.map_or_else(|| "sinal".to_string(), |code| format!("exit code {code}"));
        return Err(AlqError::ProtocolError {
            details: format!(
                "inconsistência entre código de saída ({code_desc}) e status JSON ('success')"
            ),
        });
    }

    Ok(response)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::error::ErrorCode;

    #[test]
    fn parses_valid_success_response() {
        let json = r#"{
            "schema_version": 1,
            "status": "success",
            "command": "convert",
            "input": "entrada.pdf",
            "output": "entrada.epub",
            "metadata": {
                "title": "Livro Teste",
                "author": "Autor",
                "language": "pt-BR",
                "identifier": "urn:uuid:1234"
            },
            "statistics": {
                "pages": 10,
                "pages_with_text": 10,
                "pages_without_text": 0,
                "chapters": 2,
                "paragraphs": 45,
                "images": 1,
                "page_dimensions": {
                    "width": 595.0,
                    "height": 842.0
                },
                "needs_ocr": false
            },
            "warnings": [],
            "duration_ms": 12
        }"#;

        let parsed =
            evaluate_worker_output(Some(0), json, "").expect("deve fazer parse de resposta válida");
        assert_eq!(parsed.schema_version, 1);
        assert_eq!(parsed.status, ResponseStatus::Success);
        assert_eq!(parsed.command.as_deref(), Some("convert"));
        assert_eq!(parsed.input.as_deref(), Some("entrada.pdf"));
        assert_eq!(parsed.output.as_deref(), Some("entrada.epub"));
        assert_eq!(parsed.duration_ms, Some(12));

        let stats = parsed.statistics.expect("statistics presente");
        assert_eq!(stats.pages, 10);
        assert_eq!(stats.pages_with_text, 10);
        assert_eq!(stats.pages_without_text, 0);
        assert_eq!(stats.chapters, 2);
        assert_eq!(stats.paragraphs, 45);
        assert_eq!(stats.images, 1);
        assert!(!stats.needs_ocr);
        assert_eq!(
            stats.page_dimensions,
            Some(PageDimensions {
                width: 595.0,
                height: 842.0
            })
        );
    }

    #[test]
    fn rejects_invalid_schema_version() {
        let json = r#"{"schema_version": 99, "status": "success"}"#;
        let err = evaluate_worker_output(Some(0), json, "").unwrap_err();
        assert_eq!(err.error_code(), ErrorCode::ProtocolError);
        assert_eq!(err.code(), "PROTOCOL_ERROR");
    }

    #[test]
    fn rejects_inconsistent_exit_code_and_status() {
        let success_json = r#"{"schema_version": 1, "status": "success", "warnings": []}"#;
        let err = evaluate_worker_output(Some(1), success_json, "").unwrap_err();
        assert_eq!(err.error_code(), ErrorCode::ProtocolError);

        let error_without_payload = r#"{"schema_version": 1, "status": "error", "warnings": []}"#;
        let err2 = evaluate_worker_output(Some(0), error_without_payload, "").unwrap_err();
        assert_eq!(err2.error_code(), ErrorCode::ProtocolError);
    }

    #[test]
    fn maps_structured_worker_errors_to_domain_alq_errors() {
        let json = r#"{
            "schema_version": 1,
            "status": "error",
            "error": {
                "code": "PDF_PASSWORD_REQUIRED",
                "message": "O PDF está protegido por senha."
            },
            "warnings": []
        }"#;
        let err = evaluate_worker_output(Some(1), json, "").unwrap_err();
        assert_eq!(err.error_code(), ErrorCode::PdfPasswordRequired);
        assert_eq!(err.code(), "PDF_PASSWORD_REQUIRED");
        assert!(err.to_string().contains("protegido por senha"));
    }

    #[test]
    fn empty_stdout_with_nonzero_exit_returns_python_execution_failed() {
        let err = evaluate_worker_output(Some(1), "", "ImportError: no module").unwrap_err();
        assert_eq!(err.error_code(), ErrorCode::PythonExecutionFailed);
        assert_eq!(err.code(), "PYTHON_EXECUTION_FAILED");
    }
}
