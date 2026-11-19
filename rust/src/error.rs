use std::fmt;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use thiserror::Error;

pub const EXIT_SUCCESS: i32 = 0;
pub const EXIT_RUNTIME_ERROR: i32 = 1;
pub const EXIT_VALIDATION_ERROR: i32 = 2;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ErrorCode {
    InputNotFound,
    InvalidInput,
    OutputExists,
    PythonNotFound,
    PythonExecutionFailed,
    ProtocolError,
    PdfOpenFailed,
    PdfPasswordRequired,
    NoExtractableText,
    TextExtractionFailed,
    EpubBuildFailed,
    EpubValidationFailed,
    ConversionFailed,
    IoError,
}

impl ErrorCode {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::InputNotFound => "INPUT_NOT_FOUND",
            Self::InvalidInput => "INVALID_INPUT",
            Self::OutputExists => "OUTPUT_EXISTS",
            Self::PythonNotFound => "PYTHON_NOT_FOUND",
            Self::PythonExecutionFailed => "PYTHON_EXECUTION_FAILED",
            Self::ProtocolError => "PROTOCOL_ERROR",
            Self::PdfOpenFailed => "PDF_OPEN_FAILED",
            Self::PdfPasswordRequired => "PDF_PASSWORD_REQUIRED",
            Self::NoExtractableText => "NO_EXTRACTABLE_TEXT",
            Self::TextExtractionFailed => "TEXT_EXTRACTION_FAILED",
            Self::EpubBuildFailed => "EPUB_BUILD_FAILED",
            Self::EpubValidationFailed => "EPUB_VALIDATION_FAILED",
            Self::ConversionFailed => "CONVERSION_FAILED",
            Self::IoError => "IO_ERROR",
        }
    }

    #[must_use]
    pub fn from_code_str(code: &str) -> Self {
        match code.trim() {
            "INPUT_NOT_FOUND" => Self::InputNotFound,
            "INVALID_INPUT" => Self::InvalidInput,
            "OUTPUT_EXISTS" => Self::OutputExists,
            "PYTHON_NOT_FOUND" => Self::PythonNotFound,
            "PYTHON_EXECUTION_FAILED" | "RUNNER_FAILED" => Self::PythonExecutionFailed,
            "PROTOCOL_ERROR" => Self::ProtocolError,
            "PDF_OPEN_FAILED" => Self::PdfOpenFailed,
            "PDF_PASSWORD_REQUIRED" | "ENCRYPTED_PDF" => Self::PdfPasswordRequired,
            "NO_EXTRACTABLE_TEXT" | "NO_TEXT_EXTRACTED" => Self::NoExtractableText,
            "TEXT_EXTRACTION_FAILED" => Self::TextExtractionFailed,
            "EPUB_BUILD_FAILED" => Self::EpubBuildFailed,
            "EPUB_VALIDATION_FAILED" => Self::EpubValidationFailed,
            "IO_ERROR" => Self::IoError,
            _ => Self::ConversionFailed,
        }
    }

    #[must_use]
    pub const fn exit_code(self) -> i32 {
        match self {
            Self::InputNotFound | Self::InvalidInput | Self::OutputExists => EXIT_VALIDATION_ERROR,
            Self::PythonNotFound
            | Self::PythonExecutionFailed
            | Self::ProtocolError
            | Self::PdfOpenFailed
            | Self::PdfPasswordRequired
            | Self::NoExtractableText
            | Self::TextExtractionFailed
            | Self::EpubBuildFailed
            | Self::EpubValidationFailed
            | Self::ConversionFailed
            | Self::IoError => EXIT_RUNTIME_ERROR,
        }
    }
}

impl fmt::Display for ErrorCode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Error)]
pub enum AlqError {
    #[error(
        "[INPUT_NOT_FOUND] Arquivo de entrada não encontrado: '{}'. Verifique se o caminho foi digitado corretamente.",
        path.display()
    )]
    InputNotFound { path: PathBuf },

    #[error("[INVALID_INPUT] Entrada inválida ('{}'): {reason} {hint}", path.display())]
    InvalidInput {
        path: PathBuf,
        reason: String,
        hint: String,
    },

    #[error(
        "[OUTPUT_EXISTS] O arquivo de saída '{}' já existe. Use --overwrite para permitir sobrescrever o arquivo existente.",
        path.display()
    )]
    OutputExists { path: PathBuf },

    #[error(
        "[PYTHON_NOT_FOUND] Interpretador Python não encontrado ({details}). Defina ALQ_PYTHON ou execute 'uv --directory python sync'."
    )]
    PythonNotFound { details: String },

    #[error(
        "[PYTHON_EXECUTION_FAILED] Falha na execução do worker Python: {details}. Execute novamente com --debug para investigar."
    )]
    PythonExecutionFailed { details: String },

    #[error(
        "[PROTOCOL_ERROR] Resposta inválida do worker Python: {details}. Verifique se o módulo Python 'alq' está atualizado."
    )]
    ProtocolError { details: String },

    #[error("[PDF_OPEN_FAILED] {message}{}", format_optional_hint(hint.as_deref()))]
    PdfOpenFailed {
        message: String,
        hint: Option<String>,
    },

    #[error("[PDF_PASSWORD_REQUIRED] {message}{}", format_optional_hint(hint.as_deref()))]
    PdfPasswordRequired {
        message: String,
        hint: Option<String>,
    },

    #[error("[NO_EXTRACTABLE_TEXT] {message}{}", format_optional_hint(hint.as_deref()))]
    NoExtractableText {
        message: String,
        hint: Option<String>,
    },

    #[error("[TEXT_EXTRACTION_FAILED] {message}{}", format_optional_hint(hint.as_deref()))]
    TextExtractionFailed {
        message: String,
        hint: Option<String>,
    },

    #[error("[EPUB_BUILD_FAILED] {message}{}", format_optional_hint(hint.as_deref()))]
    EpubBuildFailed {
        message: String,
        hint: Option<String>,
    },

    #[error("[EPUB_VALIDATION_FAILED] {message}{}", format_optional_hint(hint.as_deref()))]
    EpubValidationFailed {
        message: String,
        hint: Option<String>,
    },

    #[error("[{code}] {message}{}", format_optional_hint(hint.as_deref()))]
    WorkerError {
        code: String,
        message: String,
        hint: Option<String>,
    },

    #[error(
        "[IO_ERROR] Erro de leitura/escrita em '{}': {source}. Verifique as permissões do arquivo ou diretório.",
        path.display()
    )]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
}

fn format_optional_hint(hint: Option<&str>) -> String {
    match hint {
        Some(h) if !h.trim().is_empty() => format!(" {}", h.trim()),
        _ => String::new(),
    }
}

impl AlqError {
    #[must_use]
    pub fn from_worker_payload(code: String, message: String, hint: Option<String>) -> Self {
        match code.trim() {
            "PDF_OPEN_FAILED" => Self::PdfOpenFailed { message, hint },
            "PDF_PASSWORD_REQUIRED" => Self::PdfPasswordRequired { message, hint },
            "NO_EXTRACTABLE_TEXT" => Self::NoExtractableText { message, hint },
            "TEXT_EXTRACTION_FAILED" => Self::TextExtractionFailed { message, hint },
            "EPUB_BUILD_FAILED" => Self::EpubBuildFailed { message, hint },
            "EPUB_VALIDATION_FAILED" => Self::EpubValidationFailed { message, hint },
            _ => Self::WorkerError {
                code,
                message,
                hint,
            },
        }
    }

    #[must_use]
    pub fn error_code(&self) -> ErrorCode {
        match self {
            Self::InputNotFound { .. } => ErrorCode::InputNotFound,
            Self::InvalidInput { .. } => ErrorCode::InvalidInput,
            Self::OutputExists { .. } => ErrorCode::OutputExists,
            Self::PythonNotFound { .. } => ErrorCode::PythonNotFound,
            Self::PythonExecutionFailed { .. } => ErrorCode::PythonExecutionFailed,
            Self::ProtocolError { .. } => ErrorCode::ProtocolError,
            Self::PdfOpenFailed { .. } => ErrorCode::PdfOpenFailed,
            Self::PdfPasswordRequired { .. } => ErrorCode::PdfPasswordRequired,
            Self::NoExtractableText { .. } => ErrorCode::NoExtractableText,
            Self::TextExtractionFailed { .. } => ErrorCode::TextExtractionFailed,
            Self::EpubBuildFailed { .. } => ErrorCode::EpubBuildFailed,
            Self::EpubValidationFailed { .. } => ErrorCode::EpubValidationFailed,
            Self::WorkerError { code, .. } => ErrorCode::from_code_str(code),
            Self::Io { .. } => ErrorCode::IoError,
        }
    }

    #[must_use]
    pub fn code(&self) -> &str {
        match self {
            Self::WorkerError { code, .. } => code.as_str(),
            other => other.error_code().as_str(),
        }
    }

    #[must_use]
    pub fn exit_code(&self) -> i32 {
        self.error_code().exit_code()
    }
}

pub type Result<T> = std::result::Result<T, AlqError>;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn error_codes_and_exit_codes_are_consistent() {
        let not_found = AlqError::InputNotFound {
            path: PathBuf::from("ausente.pdf"),
        };
        assert_eq!(not_found.code(), "INPUT_NOT_FOUND");
        assert_eq!(not_found.exit_code(), EXIT_VALIDATION_ERROR);
        assert!(not_found.to_string().contains("INPUT_NOT_FOUND"));

        let invalid = AlqError::InvalidInput {
            path: PathBuf::from("invalido.txt"),
            reason: "extensão inválida.".into(),
            hint: "Informe um arquivo .pdf.".into(),
        };
        assert_eq!(invalid.code(), "INVALID_INPUT");
        assert_eq!(invalid.exit_code(), EXIT_VALIDATION_ERROR);

        let exists = AlqError::OutputExists {
            path: PathBuf::from("saida.epub"),
        };
        assert_eq!(exists.code(), "OUTPUT_EXISTS");
        assert_eq!(exists.exit_code(), EXIT_VALIDATION_ERROR);
        assert!(exists.to_string().contains("--overwrite"));

        let proto = AlqError::ProtocolError {
            details: "JSON malformado".into(),
        };
        assert_eq!(proto.code(), "PROTOCOL_ERROR");
        assert_eq!(proto.exit_code(), EXIT_RUNTIME_ERROR);

        let pdf_err = AlqError::from_worker_payload(
            "PDF_OPEN_FAILED".to_string(),
            "Arquivo corrompido.".to_string(),
            None,
        );
        assert_eq!(pdf_err.error_code(), ErrorCode::PdfOpenFailed);
        assert_eq!(pdf_err.code(), "PDF_OPEN_FAILED");
        assert_eq!(pdf_err.exit_code(), EXIT_RUNTIME_ERROR);
        assert!(pdf_err.to_string().contains("Arquivo corrompido."));
    }
}
