use serde::{Deserialize, Serialize};

use crate::error::{AlqError, Result};

pub const SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ResponseStatus {
    Success,
    Error,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PageDimensions {
    pub width: f64,
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

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct DocumentMetadata {
    #[serde(default)]
    pub title: Option<String>,
    #[serde(default)]
    pub author: Option<String>,
    #[serde(default)]
    pub language: Option<String>,
    #[serde(default)]
    pub identifier: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct DocumentStatistics {
    #[serde(default)]
    pub pages: usize,
    #[serde(default)]
    pub pages_with_text: usize,
    #[serde(default)]
    pub pages_without_text: usize,
    #[serde(default)]
    pub chapters: usize,
    #[serde(default)]
    pub paragraphs: usize,
    #[serde(default)]
    pub images: usize,
    #[serde(default)]
    pub page_dimensions: Option<PageDimensions>,
    #[serde(default)]
    pub needs_ocr: bool,
}

pub type ConversionStats = DocumentStatistics;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProtocolErrorPayload {
    pub code: String,
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub hint: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WorkerResponse {
    pub schema_version: u32,
    pub status: ResponseStatus,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub command: Option<String>,
    #[serde(default, alias = "input_path", skip_serializing_if = "Option::is_none")]
    pub input: Option<String>,
    #[serde(
        default,
        alias = "output_path",
        skip_serializing_if = "Option::is_none"
    )]
    pub output: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub metadata: Option<DocumentMetadata>,
    #[serde(default, alias = "stats", skip_serializing_if = "Option::is_none")]
    pub statistics: Option<DocumentStatistics>,
    #[serde(default)]
    pub warnings: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub duration_ms: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<ProtocolErrorPayload>,
}

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
