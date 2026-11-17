//! Tipos de erro explícitos (`thiserror`), códigos de erro e códigos de saída da CLI `alq`.

use std::fmt;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use thiserror::Error;

/// Código de saída para execução bem-sucedida.
pub const EXIT_SUCCESS: i32 = 0;

/// Código de saída para erros de execução, protocolo JSON, subprocesso Python ou conversão.
pub const EXIT_RUNTIME_ERROR: i32 = 1;

/// Código de saída para erros de validação de argumentos, entrada ou proteção de sobrescrita.
pub const EXIT_VALIDATION_ERROR: i32 = 2;

/// Códigos padronizados de erro da camada Rust e do protocolo.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ErrorCode {
    /// O arquivo de entrada informado não foi encontrado.
    InputNotFound,
    /// O caminho de entrada ou saída é inválido (diretório, não é PDF válido, etc.).
    InvalidInput,
    /// O arquivo de saída já existe e `--overwrite` não foi informado.
    OutputExists,
    /// O interpretador Python não foi encontrado ou não pôde ser iniciado.
    PythonNotFound,
    /// O processo Python encerrou com falha inesperada.
    RunnerFailed,
    /// O contrato JSON v1 retornado pelo worker Python é inválido ou incompatível.
    ProtocolError,
    /// O worker Python reportou erro estruturado durante o processamento.
    ConversionFailed,
    /// Erro de leitura ou escrita no sistema de arquivos.
    IoError,
}

impl ErrorCode {
    /// Retorna a representação textual canônica do código de erro.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::InputNotFound => "INPUT_NOT_FOUND",
            Self::InvalidInput => "INVALID_INPUT",
            Self::OutputExists => "OUTPUT_EXISTS",
            Self::PythonNotFound => "PYTHON_NOT_FOUND",
            Self::RunnerFailed => "RUNNER_FAILED",
            Self::ProtocolError => "PROTOCOL_ERROR",
            Self::ConversionFailed => "CONVERSION_FAILED",
            Self::IoError => "IO_ERROR",
        }
    }

    /// Retorna o código de saída de processo (`exit code`) associado a este erro.
    #[must_use]
    pub const fn exit_code(self) -> i32 {
        match self {
            Self::InputNotFound | Self::InvalidInput | Self::OutputExists => EXIT_VALIDATION_ERROR,
            Self::PythonNotFound
            | Self::RunnerFailed
            | Self::ProtocolError
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

/// Erros explícitos da biblioteca e CLI `alq`.
#[derive(Debug, Error)]
pub enum AlqError {
    /// Arquivo de entrada inexistente.
    #[error(
        "[INPUT_NOT_FOUND] Arquivo de entrada não encontrado: '{}'. Verifique se o caminho foi digitado corretamente.",
        path.display()
    )]
    InputNotFound {
        /// Caminho ausente informado pelo usuário.
        path: PathBuf,
    },

    /// Caminho de entrada ou saída inválido.
    #[error("[INVALID_INPUT] Entrada inválida ('{}'): {reason} {hint}", path.display())]
    InvalidInput {
        /// Caminho problemático.
        path: PathBuf,
        /// Motivo curto descrevendo a violação.
        reason: String,
        /// Ação recomendada ao usuário.
        hint: String,
    },

    /// O arquivo de saída já existe e `--overwrite` não foi especificado.
    #[error(
        "[OUTPUT_EXISTS] O arquivo de saída '{}' já existe. Use --overwrite para permitir sobrescrever o arquivo existente.",
        path.display()
    )]
    OutputExists {
        /// Caminho do arquivo de saída existente.
        path: PathBuf,
    },

    /// Interpretador Python não localizado.
    #[error(
        "[PYTHON_NOT_FOUND] Interpretador Python não encontrado ({details}). Defina ALQ_PYTHON ou execute 'uv --directory python sync'."
    )]
    PythonNotFound {
        /// Detalhes técnicos da tentativa de localização/execução.
        details: String,
    },

    /// Falha ao executar o subprocesso Python.
    #[error(
        "[RUNNER_FAILED] Falha na execução do worker Python: {details}. Execute novamente com --debug para investigar."
    )]
    RunnerFailed {
        /// Detalhes da falha (status de saída, stderr, etc.).
        details: String,
    },

    /// Violação do contrato JSON v1 no `stdout` do worker Python.
    #[error(
        "[PROTOCOL_ERROR] Resposta inválida do worker Python: {details}. Verifique se o módulo Python 'alq' está atualizado."
    )]
    ProtocolError {
        /// Explicação da falha de parsing ou versão incompatível.
        details: String,
    },

    /// Erro estruturado reportado pelo worker Python no payload JSON.
    #[error("[{code}] {message}{}", format_optional_hint(hint.as_deref()))]
    WorkerError {
        /// Código de erro retornado pelo Python.
        code: String,
        /// Mensagem principal retornada pelo Python.
        message: String,
        /// Dica opcional de resolução.
        hint: Option<String>,
    },

    /// Erro de entrada/saída ao inspecionar ou manipular arquivos.
    #[error(
        "[IO_ERROR] Erro de leitura/escrita em '{}': {source}. Verifique as permissões do arquivo ou diretório.",
        path.display()
    )]
    Io {
        /// Caminho relacionado à operação de E/S.
        path: PathBuf,
        /// Erro subjacente do sistema operacional.
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
    /// Retorna o enum [`ErrorCode`] associado ao erro.
    #[must_use]
    pub const fn error_code(&self) -> ErrorCode {
        match self {
            Self::InputNotFound { .. } => ErrorCode::InputNotFound,
            Self::InvalidInput { .. } => ErrorCode::InvalidInput,
            Self::OutputExists { .. } => ErrorCode::OutputExists,
            Self::PythonNotFound { .. } => ErrorCode::PythonNotFound,
            Self::RunnerFailed { .. } => ErrorCode::RunnerFailed,
            Self::ProtocolError { .. } => ErrorCode::ProtocolError,
            Self::WorkerError { .. } => ErrorCode::ConversionFailed,
            Self::Io { .. } => ErrorCode::IoError,
        }
    }

    /// Retorna a string do código de erro (ex.: `"INPUT_NOT_FOUND"`, `"INVALID_INPUT"`).
    #[must_use]
    pub fn code(&self) -> &str {
        match self {
            Self::WorkerError { code, .. } => code.as_str(),
            other => other.error_code().as_str(),
        }
    }

    /// Retorna o código de saída (`exit code`) apropriado para encerrar o processo CLI.
    #[must_use]
    pub const fn exit_code(&self) -> i32 {
        self.error_code().exit_code()
    }
}

/// Alias padrão de resultado para operações da biblioteca `alq`.
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
    }
}
