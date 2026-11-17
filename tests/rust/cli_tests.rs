//! Testes de integração da CLI Rust (`alq`), validação de caminhos e runner Python.

use std::fs::File;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;

use clap::Parser;
use tempfile::TempDir;

use alq::cli::{Cli, Commands, ConvertArgs, InspectArgs};
use alq::commands::{execute, run_convert_command, run_inspect_command};
use alq::config::{resolve_default_output_path, validate_input_pdf, ConvertConfig, InspectConfig};
use alq::error::{ErrorCode, EXIT_SUCCESS, EXIT_VALIDATION_ERROR};
use alq::protocol::ResponseStatus;
use alq::runner::PythonRunner;

/// Cria um arquivo PDF mínimo válido com assinatura mágica `%PDF-`.
fn create_valid_pdf(path: &Path) {
    let mut file = File::create(path).expect("deve criar arquivo PDF temporário");
    file.write_all(b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n")
        .expect("deve escrever conteúdo PDF mínimo");
}

#[test]
fn cli_parsing_convert_default_and_full_options() {
    let parsed_default =
        Cli::try_parse_from(["alq", "convert", "documento.pdf"]).expect("parse convert básico");
    assert_eq!(
        parsed_default.command,
        Commands::Convert(ConvertArgs {
            input: PathBuf::from("documento.pdf"),
            output: None,
            language: None,
            debug: false,
            overwrite: false,
        })
    );

    let parsed_full = Cli::try_parse_from([
        "alq",
        "convert",
        "documento.pdf",
        "-o",
        "custom.epub",
        "-l",
        "pt-BR",
        "--debug",
        "--overwrite",
    ])
    .expect("parse convert completo");
    assert_eq!(
        parsed_full.command,
        Commands::Convert(ConvertArgs {
            input: PathBuf::from("documento.pdf"),
            output: Some(PathBuf::from("custom.epub")),
            language: Some("pt-BR".to_string()),
            debug: true,
            overwrite: true,
        })
    );
}

#[test]
fn cli_parsing_inspect_with_and_without_json() {
    let inspect_default =
        Cli::try_parse_from(["alq", "inspect", "relatorio.pdf"]).expect("parse inspect sem json");
    assert_eq!(
        inspect_default.command,
        Commands::Inspect(InspectArgs {
            input: PathBuf::from("relatorio.pdf"),
            json: false,
        })
    );

    let inspect_json = Cli::try_parse_from(["alq", "inspect", "relatorio.pdf", "--json"])
        .expect("parse inspect com --json");
    assert_eq!(
        inspect_json.command,
        Commands::Inspect(InspectArgs {
            input: PathBuf::from("relatorio.pdf"),
            json: true,
        })
    );
}

#[test]
fn cli_parsing_rejects_missing_input() {
    assert!(Cli::try_parse_from(["alq"]).is_err());
    assert!(Cli::try_parse_from(["alq", "convert"]).is_err());
    assert!(Cli::try_parse_from(["alq", "inspect"]).is_err());
}

#[test]
fn config_resolves_default_and_custom_output_path() {
    let temp = TempDir::new().expect("criar tempdir");
    let sub_dir = temp.path().join("livros");
    std::fs::create_dir_all(&sub_dir).expect("criar subdiretório");

    let input = sub_dir.join("obra.original.pdf");
    create_valid_pdf(&input);

    assert_eq!(
        resolve_default_output_path(&input),
        sub_dir.join("obra.original.epub")
    );

    let args_default = ConvertArgs {
        input: input.clone(),
        output: None,
        language: None,
        debug: false,
        overwrite: false,
    };
    let config_default = ConvertConfig::from_args(&args_default).expect("config padrão válida");
    assert_eq!(config_default.output, sub_dir.join("obra.original.epub"));

    let custom_out = temp.path().join("personalizado.epub");
    let args_custom = ConvertArgs {
        input,
        output: Some(custom_out.clone()),
        language: Some("en".to_string()),
        debug: true,
        overwrite: false,
    };
    let config_custom = ConvertConfig::from_args(&args_custom).expect("config customizada válida");
    assert_eq!(config_custom.output, custom_out);
    assert_eq!(config_custom.language.as_deref(), Some("en"));
    assert!(config_custom.debug);
}

#[test]
fn validation_rejects_missing_input_with_input_not_found() {
    let temp = TempDir::new().expect("criar tempdir");
    let missing = temp.path().join("inexistente.pdf");

    let err = validate_input_pdf(&missing).expect_err("deve rejeitar arquivo inexistente");
    assert_eq!(err.error_code(), ErrorCode::InputNotFound);
    assert_eq!(err.code(), "INPUT_NOT_FOUND");
    assert_eq!(err.exit_code(), EXIT_VALIDATION_ERROR);
    assert!(err.to_string().contains("INPUT_NOT_FOUND"));
}

#[test]
fn validation_rejects_directory_as_input_with_invalid_input() {
    let temp = TempDir::new().expect("criar tempdir");

    let err = validate_input_pdf(temp.path()).expect_err("deve rejeitar diretório");
    assert_eq!(err.error_code(), ErrorCode::InvalidInput);
    assert_eq!(err.code(), "INVALID_INPUT");
    assert_eq!(err.exit_code(), EXIT_VALIDATION_ERROR);
}

#[test]
fn validation_rejects_non_pdf_files_with_invalid_input() {
    let temp = TempDir::new().expect("criar tempdir");

    // Caso 1: arquivo .txt comum
    let txt_file = temp.path().join("arquivo.txt");
    std::fs::write(&txt_file, b"Conteudo de texto simples").expect("escrever txt");
    let err_txt = validate_input_pdf(&txt_file).expect_err("deve rejeitar .txt");
    assert_eq!(err_txt.code(), "INVALID_INPUT");

    // Caso 2: arquivo .pdf falso (sem assinatura %PDF-)
    let fake_pdf = temp.path().join("falso.pdf");
    std::fs::write(&fake_pdf, b"<html>nao e um pdf</html>").expect("escrever falso pdf");
    let err_fake = validate_input_pdf(&fake_pdf).expect_err("deve rejeitar pdf sem magic bytes");
    assert_eq!(err_fake.code(), "INVALID_INPUT");
    assert_eq!(err_fake.exit_code(), EXIT_VALIDATION_ERROR);

    // Caso 3: arquivo .pdf vazio
    let empty_pdf = temp.path().join("vazio.pdf");
    std::fs::write(&empty_pdf, b"").expect("escrever pdf vazio");
    let err_empty = validate_input_pdf(&empty_pdf).expect_err("deve rejeitar pdf vazio");
    assert_eq!(err_empty.code(), "INVALID_INPUT");
}

#[test]
fn validation_protects_existing_output_and_allows_with_overwrite() {
    let temp = TempDir::new().expect("criar tempdir");
    let input = temp.path().join("entrada.pdf");
    let output = temp.path().join("entrada.epub");
    create_valid_pdf(&input);
    std::fs::write(&output, b"epub ja existente").expect("criar epub existente");

    let without_overwrite = ConvertArgs {
        input: input.clone(),
        output: None,
        language: None,
        debug: false,
        overwrite: false,
    };
    let err = ConvertConfig::from_args(&without_overwrite)
        .expect_err("deve bloquear sobrescrita sem --overwrite");
    assert_eq!(err.error_code(), ErrorCode::OutputExists);
    assert_eq!(err.code(), "OUTPUT_EXISTS");
    assert_eq!(err.exit_code(), EXIT_VALIDATION_ERROR);
    assert!(err.to_string().contains("--overwrite"));

    let with_overwrite = ConvertArgs {
        input: input.clone(),
        output: None,
        language: None,
        debug: false,
        overwrite: true,
    };
    let config =
        ConvertConfig::from_args(&with_overwrite).expect("deve permitir quando --overwrite ativo");
    assert_eq!(config.output, output);
    assert!(config.overwrite);
}

#[test]
fn validation_rejects_output_equal_to_input_or_directory() {
    let temp = TempDir::new().expect("criar tempdir");
    let input = temp.path().join("livro.pdf");
    create_valid_pdf(&input);

    let same_output = ConvertArgs {
        input: input.clone(),
        output: Some(input.clone()),
        language: None,
        debug: false,
        overwrite: true,
    };
    let err_same =
        ConvertConfig::from_args(&same_output).expect_err("deve rejeitar saída igual à entrada");
    assert_eq!(err_same.code(), "INVALID_INPUT");

    let dir_output = ConvertArgs {
        input,
        output: Some(temp.path().to_path_buf()),
        language: None,
        debug: false,
        overwrite: true,
    };
    let err_dir =
        ConvertConfig::from_args(&dir_output).expect_err("deve rejeitar diretório como saída");
    assert_eq!(err_dir.code(), "INVALID_INPUT");
}

#[test]
fn runner_invokes_python_stub_and_parses_json_response() {
    let temp = TempDir::new().expect("criar tempdir");
    let input = temp.path().join("teste.pdf");
    let output = temp.path().join("teste.epub");
    create_valid_pdf(&input);

    let runner = PythonRunner::new();

    // Testa convert via runner
    let convert_args = ConvertArgs {
        input: input.clone(),
        output: Some(output.clone()),
        language: Some("pt-BR".to_string()),
        debug: true,
        overwrite: false,
    };
    let convert_resp =
        run_convert_command(&convert_args, &runner).expect("runner deve executar convert stub");
    assert_eq!(convert_resp.schema_version, 1);
    assert_eq!(convert_resp.status, ResponseStatus::Success);
    assert_eq!(convert_resp.command.as_deref(), Some("convert"));
    assert_eq!(convert_resp.output_path.as_deref(), output.to_str());

    // Testa inspect via runner e run_inspect_command
    let inspect_args = InspectArgs {
        input: input.clone(),
        json: true,
    };
    let inspect_config = InspectConfig::from_args(&inspect_args).expect("config inspect válida");
    let inspect_resp = runner
        .run_inspect(&inspect_config)
        .expect("runner deve executar inspect stub");
    assert_eq!(inspect_resp.schema_version, 1);
    assert_eq!(inspect_resp.status, ResponseStatus::Success);
    assert_eq!(inspect_resp.command.as_deref(), Some("inspect"));

    let cmd_inspect_resp =
        run_inspect_command(&inspect_args, &runner).expect("run_inspect_command deve funcionar");
    assert_eq!(cmd_inspect_resp.schema_version, 1);

    // Testa execute completo de alto nível
    let cli = Cli {
        command: Commands::Inspect(inspect_args),
    };
    let full_resp = execute(&cli).expect("execute de alto nível deve funcionar");
    assert_eq!(full_resp.schema_version, 1);
}

#[test]
fn binary_supports_help_flags_and_exit_codes() {
    let bin = env!("CARGO_BIN_EXE_alq");

    for args in [
        &["--help"][..],
        &["convert", "--help"][..],
        &["inspect", "--help"][..],
    ] {
        let out = Command::new(bin)
            .args(args)
            .output()
            .expect("executar binário alq --help");
        assert_eq!(out.status.code(), Some(EXIT_SUCCESS));
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(!stdout.trim().is_empty());
    }

    // Entrada ausente -> código 2 (EXIT_VALIDATION_ERROR)
    let missing_arg_out = Command::new(bin)
        .arg("convert")
        .output()
        .expect("executar alq convert sem argumentos");
    assert_eq!(missing_arg_out.status.code(), Some(EXIT_VALIDATION_ERROR));

    // Arquivo inexistente -> código 2 e mensagem INPUT_NOT_FOUND
    let temp = TempDir::new().expect("criar tempdir");
    let missing_file = temp.path().join("nao_existe.pdf");
    let not_found_out = Command::new(bin)
        .args(["convert", missing_file.to_str().unwrap()])
        .output()
        .expect("executar alq convert com arquivo inexistente");
    assert_eq!(not_found_out.status.code(), Some(EXIT_VALIDATION_ERROR));
    let stderr = String::from_utf8_lossy(&not_found_out.stderr);
    assert!(stderr.contains("INPUT_NOT_FOUND"));

    // Execução ponta a ponta com PDF válido -> código 0
    let valid_pdf = temp.path().join("valido.pdf");
    create_valid_pdf(&valid_pdf);
    let ok_out = Command::new(bin)
        .args(["convert", valid_pdf.to_str().unwrap()])
        .output()
        .expect("executar alq convert com PDF válido");
    assert_eq!(ok_out.status.code(), Some(EXIT_SUCCESS));
}
