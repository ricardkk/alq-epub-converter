//! Definição declarativa dos argumentos, subcomandos e flags da CLI (`clap`).

use std::path::PathBuf;

use clap::{Args, Parser, Subcommand};

/// Interface principal de linha de comando do `alq`.
#[derive(Debug, Clone, PartialEq, Eq, Parser)]
#[command(
    name = "alq",
    version,
    about = "Conversor de arquivos PDF para EPUB baseado em terminal",
    long_about = "Orquestrador CLI em Rust para conversão e inspeção de arquivos PDF rumo ao formato EPUB."
)]
pub struct Cli {
    /// Subcomando a ser executado.
    #[command(subcommand)]
    pub command: Commands,
}

/// Subcomandos disponíveis na CLI `alq`.
#[derive(Debug, Clone, PartialEq, Eq, Subcommand)]
pub enum Commands {
    /// Converte um arquivo PDF em um pacote EPUB
    Convert(ConvertArgs),
    /// Inspeciona metadados e estrutura básica de um arquivo PDF
    Inspect(InspectArgs),
}

/// Argumentos do subcomando `alq convert`.
#[derive(Debug, Clone, PartialEq, Eq, Args)]
pub struct ConvertArgs {
    /// Caminho do arquivo PDF de entrada
    #[arg(value_name = "INPUT")]
    pub input: PathBuf,

    /// Caminho do arquivo EPUB de saída (padrão: mesmo diretório e nome da entrada com extensão .epub)
    #[arg(short = 'o', long = "output", value_name = "OUTPUT")]
    pub output: Option<PathBuf>,

    /// Código de idioma principal do documento (ex.: pt-BR, en)
    #[arg(short = 'l', long = "language", value_name = "LANG")]
    pub language: Option<String>,

    /// Ativa logs técnicos detalhados para depuração
    #[arg(long = "debug")]
    pub debug: bool,

    /// Permite sobrescrever o arquivo de saída caso já exista
    #[arg(long = "overwrite")]
    pub overwrite: bool,
}

/// Argumentos do subcomando `alq inspect`.
#[derive(Debug, Clone, PartialEq, Eq, Args)]
pub struct InspectArgs {
    /// Caminho do arquivo PDF de entrada
    #[arg(value_name = "INPUT")]
    pub input: PathBuf,

    /// Exibe o resultado da inspeção em formato JSON
    #[arg(long = "json")]
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
