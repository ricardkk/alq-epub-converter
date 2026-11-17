//! Invocação segura do worker Python (`python -m alq`) via `std::process::Command`
//! e leitura estruturada do Contrato JSON v1 no `stdout`.

use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use crate::config::{ConvertConfig, InspectConfig};
use crate::error::{AlqError, Result};
use crate::protocol::{parse_worker_response, WorkerResponse};

/// Nome da variável de ambiente principal para sobrescrever o interpretador Python.
pub const ENV_ALQ_PYTHON: &str = "ALQ_PYTHON";

/// Nome da variável de ambiente de fallback para compatibilidade com a especificação original.
pub const ENV_PDF2EPUB_PYTHON: &str = "PDF2EPUB_PYTHON";

/// Executor responsável por invocar o módulo Python `alq` em subprocesso isolado.
#[derive(Debug, Clone)]
pub struct PythonRunner {
    python_bin: PathBuf,
    python_src_dir: Option<PathBuf>,
}

impl Default for PythonRunner {
    fn default() -> Self {
        Self::new()
    }
}

impl PythonRunner {
    /// Cria um [`PythonRunner`] resolvendo automaticamente o interpretador Python e o diretório `python/src`.
    #[must_use]
    pub fn new() -> Self {
        Self {
            python_bin: resolve_python_executable(),
            python_src_dir: resolve_python_src_dir(),
        }
    }

    /// Cria um [`PythonRunner`] apontando para um executável Python explícito.
    #[must_use]
    pub fn with_executable(python_bin: impl Into<PathBuf>) -> Self {
        Self {
            python_bin: python_bin.into(),
            python_src_dir: resolve_python_src_dir(),
        }
    }

    /// Retorna o caminho do interpretador Python configurado neste runner.
    #[must_use]
    pub fn python_bin(&self) -> &Path {
        &self.python_bin
    }

    /// Executa o subcomando `convert` no worker Python e retorna a resposta validada.
    ///
    /// # Errors
    ///
    /// Retorna erro caso o Python não possa ser iniciado, falhe durante a execução
    /// ou retorne JSON inválido no `stdout`.
    pub fn run_convert(&self, config: &ConvertConfig) -> Result<WorkerResponse> {
        let mut args: Vec<OsString> = vec![
            OsString::from("-m"),
            OsString::from("alq"),
            OsString::from("convert"),
            config.input.as_os_str().to_os_string(),
            OsString::from("--output"),
            config.output.as_os_str().to_os_string(),
        ];

        if let Some(lang) = &config.language {
            args.push(OsString::from("--language"));
            args.push(OsString::from(lang));
        }

        if config.debug {
            args.push(OsString::from("--debug"));
        }

        if config.overwrite {
            args.push(OsString::from("--overwrite"));
        }

        self.run_args(&args)
    }

    /// Executa o subcomando `inspect` no worker Python e retorna a resposta validada.
    ///
    /// # Errors
    ///
    /// Retorna erro caso o Python não possa ser iniciado, falhe durante a execução
    /// ou retorne JSON inválido no `stdout`.
    pub fn run_inspect(&self, config: &InspectConfig) -> Result<WorkerResponse> {
        let args: Vec<OsString> = vec![
            OsString::from("-m"),
            OsString::from("alq"),
            OsString::from("inspect"),
            config.input.as_os_str().to_os_string(),
            OsString::from("--json"),
        ];

        self.run_args(&args)
    }

    /// Executa `python <args...>` sem uso de shell e faz o parse do `stdout` como JSON v1.
    fn run_args(&self, args: &[OsString]) -> Result<WorkerResponse> {
        let mut command = Command::new(&self.python_bin);
        command
            .args(args)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        if let Some(src_dir) = &self.python_src_dir {
            let pythonpath = match std::env::var_os("PYTHONPATH") {
                Some(existing) if !existing.is_empty() => {
                    let mut paths = vec![src_dir.clone()];
                    paths.extend(std::env::split_paths(&existing));
                    std::env::join_paths(paths).unwrap_or_else(|_| src_dir.as_os_str().to_owned())
                }
                _ => src_dir.as_os_str().to_owned(),
            };
            command.env("PYTHONPATH", pythonpath);
        }

        let output = command.output().map_err(|err| AlqError::PythonNotFound {
            details: format!("executável '{}': {err}", self.python_bin.display()),
        })?;

        let stdout_str = String::from_utf8_lossy(&output.stdout);
        let stderr_str = String::from_utf8_lossy(&output.stderr);

        if !output.status.success() {
            // Se o worker emitiu um erro JSON estruturado no stdout, priorize-o.
            if let Err(worker_err @ AlqError::WorkerError { .. }) =
                parse_worker_response(&stdout_str)
            {
                return Err(worker_err);
            }

            let status_desc = output.status.code().map_or_else(
                || "encerrado por sinal".to_string(),
                |c| format!("código {c}"),
            );
            let stderr_trimmed = stderr_str.trim();
            let details = if stderr_trimmed.is_empty() {
                format!("processo Python finalizou com {status_desc}")
            } else {
                format!("processo Python finalizou com {status_desc}: {stderr_trimmed}")
            };

            return Err(AlqError::RunnerFailed { details });
        }

        parse_worker_response(&stdout_str)
    }
}

/// Resolve o executável Python seguindo a ordem de prioridade:
/// 1. Variável de ambiente `ALQ_PYTHON`
/// 2. Variável de ambiente `PDF2EPUB_PYTHON`
/// 3. Ambiente virtual local `python/.venv/bin/python` (relativo ao diretório atual ou raiz do repositório)
/// 4. Fallback para `python3` no `PATH`
#[must_use]
pub fn resolve_python_executable() -> PathBuf {
    resolve_python_from_env_and_paths(
        std::env::var_os(ENV_ALQ_PYTHON),
        std::env::var_os(ENV_PDF2EPUB_PYTHON),
        &candidate_venv_paths(),
    )
}

fn candidate_venv_paths() -> Vec<PathBuf> {
    let mut candidates = vec![
        PathBuf::from("python/.venv/bin/python"),
        PathBuf::from("python/.venv/Scripts/python.exe"),
    ];

    if let Some(manifest_dir) = option_env!("CARGO_MANIFEST_DIR") {
        let root = Path::new(manifest_dir);
        candidates.push(root.join("python/.venv/bin/python"));
        candidates.push(root.join("python/.venv/Scripts/python.exe"));
    }

    candidates
}

fn resolve_python_src_dir() -> Option<PathBuf> {
    let cwd_candidate = PathBuf::from("python/src");
    if cwd_candidate.is_dir() {
        return std::fs::canonicalize(&cwd_candidate)
            .ok()
            .or(Some(cwd_candidate));
    }

    if let Some(manifest_dir) = option_env!("CARGO_MANIFEST_DIR") {
        let manifest_candidate = Path::new(manifest_dir).join("python/src");
        if manifest_candidate.is_dir() {
            return Some(manifest_candidate);
        }
    }

    None
}

/// Função pura auxiliar para testar a resolução de prioridade do executável Python.
#[must_use]
pub fn resolve_python_from_env_and_paths(
    alq_python: Option<OsString>,
    pdf2epub_python: Option<OsString>,
    venv_candidates: &[PathBuf],
) -> PathBuf {
    if let Some(val) = alq_python.filter(|v| !v.is_empty()) {
        return PathBuf::from(val);
    }

    if let Some(val) = pdf2epub_python.filter(|v| !v.is_empty()) {
        return PathBuf::from(val);
    }

    for candidate in venv_candidates {
        if candidate.is_file() {
            return candidate.clone();
        }
    }

    PathBuf::from("python3")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolves_python_priority_order() {
        let chosen = resolve_python_from_env_and_paths(
            Some(OsString::from("/custom/alq/python")),
            Some(OsString::from("/custom/fallback/python")),
            &[],
        );
        assert_eq!(chosen, PathBuf::from("/custom/alq/python"));

        let fallback = resolve_python_from_env_and_paths(
            None,
            Some(OsString::from("/custom/fallback/python")),
            &[],
        );
        assert_eq!(fallback, PathBuf::from("/custom/fallback/python"));

        let default_py = resolve_python_from_env_and_paths(None, None, &[]);
        assert_eq!(default_py, PathBuf::from("python3"));
    }
}
