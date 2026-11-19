use std::path::PathBuf;

use clap::{Args, Parser, Subcommand, ValueEnum};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, ValueEnum)]
pub enum OcrMode {
    #[default]
    Never,
    Auto,
    Always,
}

impl OcrMode {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Never => "never",
            Self::Auto => "auto",
            Self::Always => "always",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Parser)]
#[command(
    name = "alq",
    version,
    about = "Conversor de arquivos PDF para EPUB baseado em terminal",
    long_about = "Orquestrador CLI em Rust para conversão e inspeção de arquivos PDF rumo ao formato EPUB."
)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Commands,
}

#[derive(Debug, Clone, PartialEq, Eq, Subcommand)]
pub enum Commands {
    #[command(about = "Converte um arquivo PDF em um pacote EPUB")]
    Convert(ConvertArgs),
    #[command(about = "Inspeciona metadados e estrutura básica de um arquivo PDF")]
    Inspect(InspectArgs),
}

#[derive(Debug, Clone, PartialEq, Eq, Args)]
pub struct ConvertArgs {
    #[arg(value_name = "INPUT", help = "Caminho do arquivo PDF de entrada")]
    pub input: PathBuf,

    #[arg(
        short = 'o',
        long = "output",
        value_name = "OUTPUT",
        help = "Caminho do arquivo EPUB de saída (padrão: mesmo diretório e nome da entrada com extensão .epub)"
    )]
    pub output: Option<PathBuf>,

    #[arg(
        short = 'l',
        long = "language",
        value_name = "LANG",
        help = "Código de idioma principal do documento (ex.: pt-BR, en)"
    )]
    pub language: Option<String>,

    #[arg(long = "debug", help = "Ativa logs técnicos detalhados para depuração")]
    pub debug: bool,

    #[arg(
        long = "overwrite",
        help = "Permite sobrescrever o arquivo de saída caso já exista"
    )]
    pub overwrite: bool,

    #[arg(
        long = "ocr",
        value_name = "MODE",
        value_enum,
        default_value_t = OcrMode::Never,
        help = "Modo de OCR para páginas sem texto extraível (auto, always, never)"
    )]
    pub ocr: OcrMode,
}

#[derive(Debug, Clone, PartialEq, Eq, Args)]
pub struct InspectArgs {
    #[arg(value_name = "INPUT", help = "Caminho do arquivo PDF de entrada")]
    pub input: PathBuf,

    #[arg(long = "json", help = "Exibe o resultado da inspeção em formato JSON")]
    pub json: bool,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_convert_defaults() {
        let cli = Cli::try_parse_from(["alq", "convert", "livro.pdf"]).expect("deve fazer parse");
        assert_eq!(
            cli.command,
            Commands::Convert(ConvertArgs {
                input: PathBuf::from("livro.pdf"),
                output: None,
                language: None,
                debug: false,
                overwrite: false,
                ocr: OcrMode::Never,
            })
        );
    }

    #[test]
    fn parse_convert_all_options() {
        let cli = Cli::try_parse_from([
            "alq",
            "convert",
            "entrada.pdf",
            "--output",
            "saida.epub",
            "--language",
            "pt-BR",
            "--debug",
            "--overwrite",
            "--ocr",
            "auto",
        ])
        .expect("deve fazer parse com todas as flags");

        assert_eq!(
            cli.command,
            Commands::Convert(ConvertArgs {
                input: PathBuf::from("entrada.pdf"),
                output: Some(PathBuf::from("saida.epub")),
                language: Some("pt-BR".to_string()),
                debug: true,
                overwrite: true,
                ocr: OcrMode::Auto,
            })
        );
    }

    #[test]
    fn parse_inspect_with_and_without_json() {
        let cli_plain =
            Cli::try_parse_from(["alq", "inspect", "doc.pdf"]).expect("parse inspect simples");
        assert_eq!(
            cli_plain.command,
            Commands::Inspect(InspectArgs {
                input: PathBuf::from("doc.pdf"),
                json: false,
            })
        );

        let cli_json = Cli::try_parse_from(["alq", "inspect", "doc.pdf", "--json"])
            .expect("parse inspect json");
        assert_eq!(
            cli_json.command,
            Commands::Inspect(InspectArgs {
                input: PathBuf::from("doc.pdf"),
                json: true,
            })
        );
    }

    #[test]
    fn missing_input_fails_parsing() {
        assert!(Cli::try_parse_from(["alq", "convert"]).is_err());
        assert!(Cli::try_parse_from(["alq", "inspect"]).is_err());
    }
}
