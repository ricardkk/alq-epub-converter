use std::fmt::Write as _;
use std::path::Path;

use crate::cli::{Cli, Commands, ConvertArgs, InspectArgs};
use crate::config::{ConvertConfig, InspectConfig};
use crate::error::{AlqError, Result};
use crate::progress::init_logging;
use crate::protocol::WorkerResponse;
use crate::runner::PythonRunner;

pub fn execute(cli: &Cli) -> Result<WorkerResponse> {
    let runner = PythonRunner::new();
    execute_with_runner(cli, &runner)
}

pub fn execute_with_runner(cli: &Cli, runner: &PythonRunner) -> Result<WorkerResponse> {
    match &cli.command {
        Commands::Convert(args) => run_convert_command(args, runner),
        Commands::Inspect(args) => run_inspect_command(args, runner),
    }
}

#[must_use]
pub fn format_convert_report(default_output: &Path, response: &WorkerResponse) -> String {
    let mut out = String::new();
    let fallback_output = default_output.to_string_lossy();
    let out_display = response
        .output
        .as_deref()
        .filter(|s| !s.trim().is_empty())
        .unwrap_or(fallback_output.as_ref());

    let _ = writeln!(out, "Conversão concluída.");
    let _ = writeln!(out, "Arquivo: {out_display}");

    if let Some(stats) = &response.statistics {
        let _ = writeln!(out, "Páginas: {}", stats.pages);
        let _ = writeln!(out, "Capítulos: {}", stats.chapters);
        let _ = writeln!(out, "Parágrafos: {}", stats.paragraphs);
        let _ = writeln!(out, "Imagens: {}", stats.images);
    }

    if !response.warnings.is_empty() {
        let _ = writeln!(out, "Avisos:");
        for warning in &response.warnings {
            let _ = writeln!(out, "  - {warning}");
        }
    }

    out
}

pub fn run_convert_command(args: &ConvertArgs, runner: &PythonRunner) -> Result<WorkerResponse> {
    init_logging(args.debug);
    let config = ConvertConfig::from_args(args)?;
    let response = runner.run_convert(&config)?;

    print!("{}", format_convert_report(&config.output, &response));

    Ok(response)
}

#[must_use]
pub fn format_inspect_report(input_path: &Path, response: &WorkerResponse) -> String {
    let mut out = String::new();
    let file_display = response
        .input
        .as_deref()
        .filter(|s| !s.trim().is_empty())
        .map_or_else(|| input_path.display().to_string(), str::to_string);

    let _ = writeln!(out, "Arquivo: {file_display}");

    if let Some(stats) = &response.statistics {
        let _ = writeln!(
            out,
            "Páginas: {} (com texto: {}, sem texto: {})",
            stats.pages, stats.pages_with_text, stats.pages_without_text
        );
    } else {
        let _ = writeln!(out, "Páginas: não informado");
    }

    let meta = response.metadata.as_ref();
    let title = meta
        .and_then(|m| m.title.as_deref())
        .filter(|s| !s.trim().is_empty())
        .unwrap_or("não informado");
    let author = meta
        .and_then(|m| m.author.as_deref())
        .filter(|s| !s.trim().is_empty())
        .unwrap_or("não informado");
    let language = meta
        .and_then(|m| m.language.as_deref())
        .filter(|s| !s.trim().is_empty())
        .unwrap_or("não informado");
    let identifier = meta
        .and_then(|m| m.identifier.as_deref())
        .filter(|s| !s.trim().is_empty())
        .unwrap_or("não informado");

    let _ = writeln!(out, "Metadados:");
    let _ = writeln!(out, "  Título: {title}");
    let _ = writeln!(out, "  Autor: {author}");
    let _ = writeln!(out, "  Idioma: {language}");
    let _ = writeln!(out, "  Identificador: {identifier}");

    if let Some(stats) = &response.statistics {
        let _ = writeln!(out, "Imagens: {}", stats.images);
        if let Some(dims) = &stats.page_dimensions {
            let _ = writeln!(
                out,
                "Dimensões da página: {:.2} x {:.2} pt",
                dims.width, dims.height
            );
        } else {
            let _ = writeln!(out, "Dimensões da página: não informado");
        }
        let _ = writeln!(
            out,
            "Necessidade provável de OCR: {}",
            if stats.needs_ocr { "Sim" } else { "Não" }
        );
    }

    if !response.warnings.is_empty() {
        let _ = writeln!(out, "Avisos:");
        for warning in &response.warnings {
            let _ = writeln!(out, "  - {warning}");
        }
    }

    out
}

pub fn run_inspect_command(args: &InspectArgs, runner: &PythonRunner) -> Result<WorkerResponse> {
    init_logging(false);
    let config = InspectConfig::from_args(args)?;
    let response = runner.run_inspect(&config)?;

    if config.json {
        let pretty_json =
            serde_json::to_string_pretty(&response).map_err(|err| AlqError::ProtocolError {
                details: format!("falha ao serializar resposta JSON: {err}"),
            })?;
        println!("{pretty_json}");
    } else {
        print!("{}", format_inspect_report(&config.input, &response));
    }

    Ok(response)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::{
        DocumentMetadata, DocumentStatistics, PageDimensions, ResponseStatus, SCHEMA_VERSION,
    };

    #[test]
    fn format_convert_report_displays_all_section_8_1_fields() {
        let response = WorkerResponse {
            schema_version: SCHEMA_VERSION,
            status: ResponseStatus::Success,
            command: Some("convert".to_string()),
            input: Some("livro.pdf".to_string()),
            output: Some("livro.epub".to_string()),
            metadata: None,
            statistics: Some(DocumentStatistics {
                pages: 10,
                pages_with_text: 10,
                pages_without_text: 0,
                chapters: 2,
                paragraphs: 25,
                images: 1,
                page_dimensions: None,
                needs_ocr: false,
            }),
            warnings: vec!["Aviso de teste.".to_string()],
            duration_ms: Some(42),
            error: None,
        };

        let report = format_convert_report(Path::new("livro.epub"), &response);
        assert!(report.contains("Conversão concluída."));
        assert!(report.contains("Arquivo: livro.epub"));
        assert!(report.contains("Páginas: 10"));
        assert!(report.contains("Capítulos: 2"));
        assert!(report.contains("Parágrafos: 25"));
        assert!(report.contains("Imagens: 1"));
        assert!(report.contains("Avisos:"));
        assert!(report.contains("Aviso de teste."));
    }

    #[test]
    fn format_inspect_report_displays_all_section_8_2_fields() {
        let response = WorkerResponse {
            schema_version: SCHEMA_VERSION,
            status: ResponseStatus::Success,
            command: Some("inspect".to_string()),
            input: Some("obra.pdf".to_string()),
            output: None,
            metadata: Some(DocumentMetadata {
                title: None,
                author: None,
                language: Some("und".to_string()),
                identifier: None,
            }),
            statistics: Some(DocumentStatistics {
                pages: 3,
                pages_with_text: 0,
                pages_without_text: 3,
                chapters: 0,
                paragraphs: 0,
                images: 3,
                page_dimensions: Some(PageDimensions {
                    width: 595.0,
                    height: 842.0,
                }),
                needs_ocr: true,
            }),
            warnings: vec![
                "Nenhum texto extraível encontrado; o documento parece ser escaneado e exigirá OCR."
                    .to_string(),
            ],
            duration_ms: Some(10),
            error: None,
        };

        let report = format_inspect_report(Path::new("obra.pdf"), &response);
        assert!(report.contains("Arquivo: obra.pdf"));
        assert!(report.contains("Páginas: 3 (com texto: 0, sem texto: 3)"));
        assert!(report.contains("Título: não informado"));
        assert!(report.contains("Autor: não informado"));
        assert!(report.contains("Idioma: und"));
        assert!(report.contains("Identificador: não informado"));
        assert!(report.contains("Imagens: 3"));
        assert!(report.contains("Dimensões da página: 595.00 x 842.00 pt"));
        assert!(report.contains("Necessidade provável de OCR: Sim"));
        assert!(report.contains("Avisos:"));
        assert!(report.contains("exigirá OCR"));
    }
}
