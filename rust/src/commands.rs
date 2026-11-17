//! Orquestração e execução dos subcomandos da CLI `alq`.

use crate::cli::{Cli, Commands, ConvertArgs, InspectArgs};
use crate::config::{ConvertConfig, InspectConfig};
use crate::error::{AlqError, Result};
use crate::progress::init_logging;
use crate::protocol::WorkerResponse;
use crate::runner::PythonRunner;

/// Executa o comando selecionado na CLI usando o [`PythonRunner`] padrão.
///
/// # Errors
///
/// Retorna erro se a validação de caminhos falhar ou se a execução do worker Python falhar.
pub fn execute(cli: &Cli) -> Result<WorkerResponse> {
    let runner = PythonRunner::new();
    execute_with_runner(cli, &runner)
}

/// Executa o comando selecionado na CLI utilizando um [`PythonRunner`] específico.
///
/// # Errors
///
/// Retorna erro se a validação de argumentos/caminhos falhar ou se o worker retornar erro.
pub fn execute_with_runner(cli: &Cli, runner: &PythonRunner) -> Result<WorkerResponse> {
    match &cli.command {
        Commands::Convert(args) => run_convert_command(args, runner),
        Commands::Inspect(args) => run_inspect_command(args, runner),
    }
}

/// Valida os argumentos e executa o fluxo de `alq convert`.
///
/// # Errors
///
/// Retorna erro de validação (`INPUT_NOT_FOUND`, `INVALID_INPUT`, `OUTPUT_EXISTS`)
/// ou erro de execução/protocolo do subprocesso Python.
pub fn run_convert_command(args: &ConvertArgs, runner: &PythonRunner) -> Result<WorkerResponse> {
    init_logging(args.debug);
    let config = ConvertConfig::from_args(args)?;
    let response = runner.run_convert(&config)?;

    let fallback_output = config.output.to_string_lossy();
    let out_display = response
        .output
        .as_deref()
        .unwrap_or(fallback_output.as_ref());
    println!(
        "Conversão concluída: '{}' -> '{}'",
        config.input.display(),
        out_display
    );

    Ok(response)
}

/// Valida os argumentos e executa o fluxo de `alq inspect`.
///
/// # Errors
///
/// Retorna erro de validação (`INPUT_NOT_FOUND`, `INVALID_INPUT`)
/// ou erro de execução/protocolo do subprocesso Python.
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
        println!("Inspeção do arquivo: '{}'", config.input.display());
        if let Some(meta) = &response.metadata {
            println!(
                "  Título: {}",
                meta.title.as_deref().unwrap_or("(não informado)")
            );
            println!(
                "  Autor: {}",
                meta.author.as_deref().unwrap_or("(não informado)")
            );
            println!(
                "  Idioma: {}",
                meta.language.as_deref().unwrap_or("(não detectado)")
            );
            println!(
                "  Identificador: {}",
                meta.identifier.as_deref().unwrap_or("(não informado)")
            );
        }
        if let Some(stats) = &response.statistics {
            println!("  Páginas: {}", stats.pages);
            println!("  Páginas com texto: {}", stats.pages_with_text);
            println!("  Páginas sem texto: {}", stats.pages_without_text);
            println!("  Capítulos: {}", stats.chapters);
            println!("  Parágrafos: {}", stats.paragraphs);
            println!("  Imagens: {}", stats.images);
            println!(
                "  Requer OCR: {}",
                if stats.needs_ocr { "sim" } else { "não" }
            );
        }
    }

    Ok(response)
}
