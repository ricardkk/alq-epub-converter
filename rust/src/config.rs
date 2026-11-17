//! Resolução de configurações, validação de caminhos de entrada/saída e regras de segurança.

use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};

use crate::cli::{ConvertArgs, InspectArgs};
use crate::error::{AlqError, Result};

/// Assinatura mágica exigida no cabeçalho de todo arquivo PDF válido.
pub const PDF_MAGIC_HEADER: &[u8; 5] = b"%PDF-";

/// Configuração validada pronta para execução do comando `alq convert`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConvertConfig {
    /// Caminho do arquivo PDF de entrada validado.
    pub input: PathBuf,
    /// Caminho resolvido para o arquivo EPUB de saída.
    pub output: PathBuf,
    /// Código de idioma opcional (ex.: `pt-BR`, `en`).
    pub language: Option<String>,
    /// Se logs de depuração estão habilitados.
    pub debug: bool,
    /// Se sobrescrita do arquivo de saída existente é permitida.
    pub overwrite: bool,
}

/// Configuração validada pronta para execução do comando `alq inspect`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InspectConfig {
    /// Caminho do arquivo PDF de entrada validado.
    pub input: PathBuf,
    /// Se a saída deve ser impressa como JSON bruto no `stdout`.
    pub json: bool,
}

/// Resolve o caminho padrão de saída `.epub` no mesmo diretório e com o mesmo nome-base da entrada.
#[must_use]
pub fn resolve_default_output_path(input: &Path) -> PathBuf {
    input.with_extension("epub")
}

/// Valida que o caminho de entrada existe, é um arquivo regular e representa um PDF válido.
///
/// # Errors
///
/// - [`AlqError::InputNotFound`] se o caminho não existir.
/// - [`AlqError::InvalidInput`] se for um diretório, não tiver extensão `.pdf` (case-insensitive)
///   ou não iniciar com a assinatura mágica `%PDF-`.
/// - [`AlqError::Io`] se ocorrer falha de leitura no sistema de arquivos.
pub fn validate_input_pdf(input: &Path) -> Result<()> {
    if !input.exists() {
        return Err(AlqError::InputNotFound {
            path: input.to_path_buf(),
        });
    }

    if input.is_dir() {
        return Err(AlqError::InvalidInput {
            path: input.to_path_buf(),
            reason: "o caminho informado é um diretório.".to_string(),
            hint: "Informe o caminho de um arquivo PDF (.pdf).".to_string(),
        });
    }

    let has_pdf_extension = input
        .extension()
        .and_then(|ext| ext.to_str())
        .is_some_and(|ext| ext.eq_ignore_ascii_case("pdf"));

    if !has_pdf_extension {
        return Err(AlqError::InvalidInput {
            path: input.to_path_buf(),
            reason: "extensão de arquivo inválida (esperado .pdf).".to_string(),
            hint: "Informe um arquivo PDF com extensão .pdf.".to_string(),
        });
    }

    let mut file = File::open(input).map_err(|source| AlqError::Io {
        path: input.to_path_buf(),
        source,
    })?;

    let mut header = [0_u8; 5];
    let bytes_read = file.read(&mut header).map_err(|source| AlqError::Io {
        path: input.to_path_buf(),
        source,
    })?;

    if bytes_read < PDF_MAGIC_HEADER.len() || &header != PDF_MAGIC_HEADER {
        return Err(AlqError::InvalidInput {
            path: input.to_path_buf(),
            reason: "o arquivo não possui assinatura mágica PDF válida ('%PDF-').".to_string(),
            hint: "Verifique se o arquivo é um documento PDF válido e não está corrompido."
                .to_string(),
        });
    }

    Ok(())
}

/// Verifica se dois caminhos apontam para o mesmo arquivo (comparação direta ou canônica).
fn paths_refer_to_same_file(a: &Path, b: &Path) -> bool {
    if a == b {
        return true;
    }
    if let (Ok(canon_a), Ok(canon_b)) = (std::fs::canonicalize(a), std::fs::canonicalize(b)) {
        return canon_a == canon_b;
    }
    false
}

impl ConvertConfig {
    /// Constrói e valida [`ConvertConfig`] a partir dos argumentos da CLI.
    ///
    /// # Errors
    ///
    /// Retorna erro se a entrada for inválida/inexistente, se a saída for um diretório
    /// ou coincidir com a entrada, ou se o arquivo de saída já existir sem `--overwrite`.
    pub fn from_args(args: &ConvertArgs) -> Result<Self> {
        validate_input_pdf(&args.input)?;

        let output = args
            .output
            .clone()
            .unwrap_or_else(|| resolve_default_output_path(&args.input));

        if output.is_dir() {
            return Err(AlqError::InvalidInput {
                path: output,
                reason: "o caminho de saída aponta para um diretório existente.".to_string(),
                hint: "Informe um caminho de arquivo com extensão .epub (ex.: -o saida.epub)."
                    .to_string(),
            });
        }

        if paths_refer_to_same_file(&args.input, &output) {
            return Err(AlqError::InvalidInput {
                path: output,
                reason: "o caminho de saída não pode ser igual ao arquivo de entrada.".to_string(),
                hint: "Informe um arquivo de saída .epub diferente do arquivo PDF de entrada."
                    .to_string(),
            });
        }

        if output.exists() && !args.overwrite {
            return Err(AlqError::OutputExists { path: output });
        }

        if let Some(lang) = &args.language {
            if lang.trim().is_empty() {
                return Err(AlqError::InvalidInput {
                    path: args.input.clone(),
                    reason: "o código de idioma informado está vazio.".to_string(),
                    hint: "Informe uma tag de idioma válida (ex.: --language pt-BR).".to_string(),
                });
            }
        }

        Ok(Self {
            input: args.input.clone(),
            output,
            language: args.language.clone(),
            debug: args.debug,
            overwrite: args.overwrite,
        })
    }
}

impl InspectConfig {
    /// Constrói e valida [`InspectConfig`] a partir dos argumentos da CLI.
    ///
    /// # Errors
    ///
    /// Retorna erro se o arquivo de entrada não existir ou não for um PDF válido.
    pub fn from_args(args: &InspectArgs) -> Result<Self> {
        validate_input_pdf(&args.input)?;

        Ok(Self {
            input: args.input.clone(),
            json: args.json,
        })
    }
}

#[cfg(test)]
mod tests {
    use std::io::Write;

    use tempfile::TempDir;

    use super::*;

    fn write_sample_pdf(path: &Path) {
        let mut f = File::create(path).expect("criar pdf de teste");
        f.write_all(b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n")
            .expect("escrever cabeçalho PDF");
    }

    #[test]
    fn default_output_path_uses_same_dir_and_epub_extension() {
        let input = Path::new("/tmp/livros/meu_livro.pdf");
        assert_eq!(
            resolve_default_output_path(input),
            PathBuf::from("/tmp/livros/meu_livro.epub")
        );
    }

    #[test]
    fn rejects_missing_input_with_input_not_found() {
        let temp = TempDir::new().unwrap();
        let missing = temp.path().join("nao_existe.pdf");

        let args = ConvertArgs {
            input: missing,
            output: None,
            language: None,
            debug: false,
            overwrite: false,
        };

        let err = ConvertConfig::from_args(&args).unwrap_err();
        assert_eq!(err.code(), "INPUT_NOT_FOUND");
    }

    #[test]
    fn rejects_directory_as_input_with_invalid_input() {
        let temp = TempDir::new().unwrap();
        let args = ConvertArgs {
            input: temp.path().to_path_buf(),
            output: None,
            language: None,
            debug: false,
            overwrite: false,
        };

        let err = ConvertConfig::from_args(&args).unwrap_err();
        assert_eq!(err.code(), "INVALID_INPUT");
    }

    #[test]
    fn rejects_non_pdf_file_or_bad_magic_header() {
        let temp = TempDir::new().unwrap();

        let txt_path = temp.path().join("nota.txt");
        std::fs::write(&txt_path, b"%PDF-1.4 texto").unwrap();
        let err_txt = validate_input_pdf(&txt_path).unwrap_err();
        assert_eq!(err_txt.code(), "INVALID_INPUT");

        let fake_pdf = temp.path().join("falso.pdf");
        std::fs::write(&fake_pdf, b"Isto nao e um PDF").unwrap();
        let err_fake = validate_input_pdf(&fake_pdf).unwrap_err();
        assert_eq!(err_fake.code(), "INVALID_INPUT");
    }

    #[test]
    fn protects_existing_output_unless_overwrite_is_set() {
        let temp = TempDir::new().unwrap();
        let input = temp.path().join("livro.pdf");
        let output = temp.path().join("livro.epub");
        write_sample_pdf(&input);
        std::fs::write(&output, b"epub existente").unwrap();

        let args_no_overwrite = ConvertArgs {
            input: input.clone(),
            output: None,
            language: None,
            debug: false,
            overwrite: false,
        };
        let err = ConvertConfig::from_args(&args_no_overwrite).unwrap_err();
        assert_eq!(err.code(), "OUTPUT_EXISTS");

        let args_overwrite = ConvertArgs {
            input,
            output: None,
            language: None,
            debug: false,
            overwrite: true,
        };
        let config = ConvertConfig::from_args(&args_overwrite).expect("deve aceitar com overwrite");
        assert_eq!(config.output, output);
    }
}
