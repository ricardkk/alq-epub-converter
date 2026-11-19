use std::fs::File;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;

use clap::Parser;
use tempfile::TempDir;

use alq::cli::{Cli, Commands, ConvertArgs, InspectArgs};
use alq::commands::{execute, run_convert_command, run_inspect_command};
use alq::config::{resolve_default_output_path, validate_input_pdf, ConvertConfig, InspectConfig};
use alq::error::{ErrorCode, EXIT_RUNTIME_ERROR, EXIT_SUCCESS, EXIT_VALIDATION_ERROR};
use alq::progress::{parse_stage_line, ProgressReporter, StageEvent};
use alq::protocol::{
    evaluate_worker_output, parse_worker_response, PageDimensions, ResponseStatus,
};
use alq::runner::PythonRunner;

fn create_valid_pdf(path: &Path) {
    const MINIMAL_VALID_PDF: &[u8] = b"%PDF-1.7\n%\xc2\xb5\xc2\xb6\n% Written by MuPDF 1.28.6\n\n1 0 obj\n<</Type/Catalog/Pages 2 0 R/Lang(pt-BR)>>\nendobj\n\n2 0 obj\n<</Type/Pages/Count 1/Kids[4 0 R]>>\nendobj\n\n3 0 obj\n<</Font<</F1 5 0 R>>>>\nendobj\n\n4 0 obj\n<</Type/Page/MediaBox[0 0 595 842]/Resources 3 0 R/Parent 2 0 R/Contents 6 0 R>>\nendobj\n\n5 0 obj\n<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>\nendobj\n\n6 0 obj\n<</Length 53>>\nstream\nBT /F1 12 Tf 72 720 Td (Ola Mundo PDF de Teste) Tj ET\nendstream\nendobj\n\n7 0 obj\n<</Title(Documento de Teste)/Author(Autor Teste)>>\nendobj\n\nxref\n0 8\n0000000000 65535 f \n0000000042 00000 n \n0000000100 00000 n \n0000000152 00000 n \n0000000191 00000 n \n0000000288 00000 n \n0000000352 00000 n \n0000000454 00000 n \n\ntrailer\n<</Size 8/Info 7 0 R/Root 1 0 R/ID[<C390C28CC28FC39E527B10C2B17B2823><97EA888DA8C8DE754DB04BD6D799DC89>]>>\nstartxref\n521\n%%EOF\n";

    let mut file = File::create(path).expect("deve criar arquivo PDF temporário");
    file.write_all(MINIMAL_VALID_PDF)
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

    let txt_file = temp.path().join("arquivo.txt");
    std::fs::write(&txt_file, b"Conteudo de texto simples").expect("escrever txt");
    let err_txt = validate_input_pdf(&txt_file).expect_err("deve rejeitar .txt");
    assert_eq!(err_txt.code(), "INVALID_INPUT");

    let fake_pdf = temp.path().join("falso.pdf");
    std::fs::write(&fake_pdf, b"<html>nao e um pdf</html>").expect("escrever falso pdf");
    let err_fake = validate_input_pdf(&fake_pdf).expect_err("deve rejeitar pdf sem magic bytes");
    assert_eq!(err_fake.code(), "INVALID_INPUT");
    assert_eq!(err_fake.exit_code(), EXIT_VALIDATION_ERROR);

    let empty_pdf = temp.path().join("vazio.pdf");
    std::fs::write(&empty_pdf, b"").expect("escrever pdf vazio");
    let err_empty = validate_input_pdf(&empty_pdf).expect_err("deve rejeitar pdf vazio");
    assert_eq!(err_empty.code(), "INVALID_INPUT");

    let short_pdf = temp.path().join("curto.pdf");
    std::fs::write(&short_pdf, b"%PDF").expect("escrever pdf curto");
    let err_short =
        validate_input_pdf(&short_pdf).expect_err("deve rejeitar pdf menor que 5 bytes");
    assert_eq!(err_short.code(), "INVALID_INPUT");
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
fn contract_json_v1_validates_convert_and_inspect_success_payloads() {
    let convert_json = r#"{
        "schema_version": 1,
        "status": "success",
        "command": "convert",
        "input": "/tmp/livro.pdf",
        "output": "/tmp/livro.epub",
        "metadata": {
            "title": "Dom Casmurro",
            "author": "Machado de Assis",
            "language": "pt-BR",
            "identifier": "urn:uuid:00000000-0000-0000-0000-000000000001"
        },
        "statistics": {
            "pages": 120,
            "pages_with_text": 118,
            "pages_without_text": 2,
            "chapters": 15,
            "paragraphs": 850,
            "images": 3,
            "page_dimensions": {
                "width": 595.0,
                "height": 842.0
            },
            "needs_ocr": false
        },
        "warnings": ["Página 2 sem camada de texto."],
        "duration_ms": 420
    }"#;

    let resp = evaluate_worker_output(Some(0), convert_json, "").expect("parse convert ok");
    assert_eq!(resp.schema_version, 1);
    assert_eq!(resp.status, ResponseStatus::Success);
    assert_eq!(resp.input.as_deref(), Some("/tmp/livro.pdf"));
    assert_eq!(resp.output.as_deref(), Some("/tmp/livro.epub"));
    assert_eq!(resp.duration_ms, Some(420));
    assert_eq!(resp.warnings, vec!["Página 2 sem camada de texto."]);

    let meta = resp.metadata.expect("metadata presente");
    assert_eq!(meta.title.as_deref(), Some("Dom Casmurro"));
    assert_eq!(meta.author.as_deref(), Some("Machado de Assis"));
    assert_eq!(meta.language.as_deref(), Some("pt-BR"));
    assert_eq!(
        meta.identifier.as_deref(),
        Some("urn:uuid:00000000-0000-0000-0000-000000000001")
    );

    let stats = resp.statistics.expect("statistics presente");
    assert_eq!(stats.pages, 120);
    assert_eq!(stats.pages_with_text, 118);
    assert_eq!(stats.pages_without_text, 2);
    assert_eq!(stats.chapters, 15);
    assert_eq!(stats.paragraphs, 850);
    assert_eq!(stats.images, 3);
    assert!(!stats.needs_ocr);
    assert_eq!(
        stats.page_dimensions,
        Some(PageDimensions {
            width: 595.0,
            height: 842.0
        })
    );

    let inspect_json = r#"{
        "schema_version": 1,
        "status": "success",
        "command": "inspect",
        "input": "/tmp/relatorio.pdf",
        "metadata": {
            "title": "Relatório",
            "author": null,
            "language": "pt-BR",
            "identifier": null
        },
        "statistics": {
            "pages": 5,
            "pages_with_text": 0,
            "pages_without_text": 5,
            "chapters": 0,
            "paragraphs": 0,
            "images": 5,
            "page_dimensions": {
                "width": 612.0,
                "height": 792.0
            },
            "needs_ocr": true
        },
        "warnings": [],
        "duration_ms": 15
    }"#;

    let inspect_resp = evaluate_worker_output(Some(0), inspect_json, "").expect("parse inspect ok");
    assert_eq!(inspect_resp.output, None);
    assert!(inspect_resp.statistics.expect("stats").needs_ocr);
}

#[test]
fn contract_json_v1_validates_errors_schema_and_status_consistency() {
    for (code, expected_enum) in [
        ("PDF_OPEN_FAILED", ErrorCode::PdfOpenFailed),
        ("PDF_PASSWORD_REQUIRED", ErrorCode::PdfPasswordRequired),
        ("NO_EXTRACTABLE_TEXT", ErrorCode::NoExtractableText),
        ("TEXT_EXTRACTION_FAILED", ErrorCode::TextExtractionFailed),
        ("EPUB_BUILD_FAILED", ErrorCode::EpubBuildFailed),
        ("EPUB_VALIDATION_FAILED", ErrorCode::EpubValidationFailed),
        ("INVALID_INPUT", ErrorCode::InvalidInput),
        ("INPUT_NOT_FOUND", ErrorCode::InputNotFound),
    ] {
        let err_json = format!(
            r#"{{
                "schema_version": 1,
                "status": "error",
                "error": {{
                    "code": "{code}",
                    "message": "Mensagem de teste para {code}"
                }},
                "warnings": []
            }}"#
        );
        let err = evaluate_worker_output(Some(1), &err_json, "").expect_err("deve retornar erro");
        assert_eq!(err.error_code(), expected_enum);
        assert_eq!(err.code(), code);
        assert!(err
            .to_string()
            .contains(&format!("Mensagem de teste para {code}")));
    }

    let bad_schema = r#"{"schema_version": 2, "status": "success", "warnings": []}"#;
    let err_schema = parse_worker_response(bad_schema).expect_err("deve rejeitar schema_version 2");
    assert_eq!(err_schema.error_code(), ErrorCode::ProtocolError);

    let malformed = "{ isto nao e json valido ";
    let err_malformed =
        evaluate_worker_output(Some(0), malformed, "").expect_err("deve rejeitar JSON malformado");
    assert_eq!(err_malformed.error_code(), ErrorCode::ProtocolError);

    let ok_json = r#"{"schema_version": 1, "status": "success", "warnings": []}"#;
    let err_inconsistent_1 = evaluate_worker_output(Some(1), ok_json, "")
        .expect_err("deve rejeitar exit_code 1 com status success");
    assert_eq!(err_inconsistent_1.error_code(), ErrorCode::ProtocolError);

    let err_no_payload = r#"{"schema_version": 1, "status": "error", "warnings": []}"#;
    let err_inconsistent_2 = evaluate_worker_output(Some(0), err_no_payload, "")
        .expect_err("deve rejeitar status error sem payload");
    assert_eq!(err_inconsistent_2.error_code(), ErrorCode::ProtocolError);

    let err_crash = evaluate_worker_output(Some(1), "", "Traceback: erro fatal")
        .expect_err("deve retornar PYTHON_EXECUTION_FAILED");
    assert_eq!(err_crash.error_code(), ErrorCode::PythonExecutionFailed);
}

#[test]
fn progress_parser_and_reporter_handle_stage_lines() {
    let stage = parse_stage_line("STAGE:2/5:Extraindo imagens").expect("stage válido");
    assert_eq!(
        stage,
        StageEvent {
            current: 2,
            total: 5,
            message: "Extraindo imagens".to_string()
        }
    );

    let mut reporter = ProgressReporter::new(false);
    reporter.handle_stderr_line("STAGE:1/3:Etapa 1");
    reporter.handle_stderr_line("DEBUG: linha técnica");
    reporter.handle_stderr_line("STAGE:3/3:Concluído");
    reporter.finish();
    assert_eq!(reporter.stages().len(), 2);
}

#[test]
fn runner_invokes_python_stub_and_parses_json_response() {
    let temp = TempDir::new().expect("criar tempdir");
    let input = temp.path().join("teste.pdf");
    let output = temp.path().join("teste.epub");
    create_valid_pdf(&input);

    let runner = PythonRunner::new();

    let convert_args = ConvertArgs {
        input: input.clone(),
        output: Some(output.clone()),
        language: Some("pt-BR".to_string()),
        debug: true,
        overwrite: false,
    };
    let convert_resp =
        run_convert_command(&convert_args, &runner).expect("runner deve executar convert real");
    assert_eq!(convert_resp.schema_version, 1);
    assert_eq!(convert_resp.status, ResponseStatus::Success);
    assert_eq!(convert_resp.command.as_deref(), Some("convert"));
    assert_eq!(convert_resp.output.as_deref(), output.to_str());
    assert!(convert_resp.statistics.is_some());
    assert!(output.is_file());
    assert!(std::fs::metadata(&output).expect("metadata epub").len() > 0);

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
    assert_eq!(inspect_resp.output, None);

    let cmd_inspect_resp =
        run_inspect_command(&inspect_args, &runner).expect("run_inspect_command deve funcionar");
    assert_eq!(cmd_inspect_resp.schema_version, 1);

    let cli = Cli {
        command: Commands::Inspect(inspect_args),
    };
    let full_resp = execute(&cli).expect("execute de alto nível deve funcionar");
    assert_eq!(full_resp.schema_version, 1);
}

#[test]
fn runner_handles_simulated_worker_error_and_missing_python_binary() {
    let temp = TempDir::new().expect("criar tempdir");
    let input = temp.path().join("simulado.pdf");
    create_valid_pdf(&input);

    let convert_args = ConvertArgs {
        input: input.clone(),
        output: None,
        language: None,
        debug: true,
        overwrite: false,
    };

    let runner_sim_err = PythonRunner::new().with_env("ALQ_SIMULATE_ERROR", "PDF_OPEN_FAILED");
    let err = run_convert_command(&convert_args, &runner_sim_err)
        .expect_err("deve capturar erro estruturado vindo do Python");
    assert_eq!(err.error_code(), ErrorCode::PdfOpenFailed);
    assert_eq!(err.code(), "PDF_OPEN_FAILED");
    assert_eq!(err.exit_code(), EXIT_RUNTIME_ERROR);
    assert!(err.to_string().contains("PDF_OPEN_FAILED"));

    let runner_missing_py =
        PythonRunner::with_executable("/caminho/inexistente/python_nao_existe_alq");
    let err_missing = run_convert_command(&convert_args, &runner_missing_py)
        .expect_err("deve retornar PYTHON_NOT_FOUND");
    assert_eq!(err_missing.error_code(), ErrorCode::PythonNotFound);
    assert_eq!(err_missing.code(), "PYTHON_NOT_FOUND");
    assert_eq!(err_missing.exit_code(), EXIT_RUNTIME_ERROR);
}

#[test]
fn binary_supports_help_flags_simulated_errors_and_exit_codes() {
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

    let missing_arg_out = Command::new(bin)
        .arg("convert")
        .output()
        .expect("executar alq convert sem argumentos");
    assert_eq!(missing_arg_out.status.code(), Some(EXIT_VALIDATION_ERROR));

    let temp = TempDir::new().expect("criar tempdir");
    let missing_file = temp.path().join("nao_existe.pdf");
    let not_found_out = Command::new(bin)
        .args(["convert", missing_file.to_str().unwrap()])
        .output()
        .expect("executar alq convert com arquivo inexistente");
    assert_eq!(not_found_out.status.code(), Some(EXIT_VALIDATION_ERROR));
    let stderr = String::from_utf8_lossy(&not_found_out.stderr);
    assert!(stderr.contains("INPUT_NOT_FOUND"));

    let valid_pdf = temp.path().join("valido.pdf");
    let expected_epub = temp.path().join("valido.epub");
    create_valid_pdf(&valid_pdf);
    let ok_out = Command::new(bin)
        .args(["convert", valid_pdf.to_str().unwrap()])
        .output()
        .expect("executar alq convert com PDF válido");
    assert_eq!(ok_out.status.code(), Some(EXIT_SUCCESS));
    assert!(expected_epub.is_file());
    let ok_stdout = String::from_utf8_lossy(&ok_out.stdout);
    assert!(ok_stdout.contains("Conversão concluída."));
    assert!(ok_stdout.contains("Páginas: 1"));
    assert!(ok_stdout.contains("Capítulos: 1"));
    assert!(ok_stdout.contains("Parágrafos: 1"));

    let sim_err_out = Command::new(bin)
        .env("ALQ_SIMULATE_ERROR", "PDF_PASSWORD_REQUIRED")
        .args(["inspect", valid_pdf.to_str().unwrap(), "--json"])
        .output()
        .expect("executar alq inspect com erro simulado");
    assert_eq!(sim_err_out.status.code(), Some(EXIT_RUNTIME_ERROR));
    let sim_stderr = String::from_utf8_lossy(&sim_err_out.stderr);
    assert!(sim_stderr.contains("PDF_PASSWORD_REQUIRED"));

    let bad_py_out = Command::new(bin)
        .env("ALQ_PYTHON", "/caminho/inexistente/python_invalido")
        .args(["inspect", valid_pdf.to_str().unwrap()])
        .output()
        .expect("executar alq inspect com ALQ_PYTHON inválido");
    assert_eq!(bad_py_out.status.code(), Some(EXIT_RUNTIME_ERROR));
    let bad_py_stderr = String::from_utf8_lossy(&bad_py_out.stderr);
    assert!(bad_py_stderr.contains("PYTHON_NOT_FOUND"));
}

#[test]
fn inspect_real_valid_and_corrupted_pdf_end_to_end() {
    let bin = env!("CARGO_BIN_EXE_alq");
    let temp = TempDir::new().expect("criar tempdir");

    let valid_pdf = temp.path().join("livro_real.pdf");
    create_valid_pdf(&valid_pdf);

    let inspect_text_out = Command::new(bin)
        .args(["inspect", valid_pdf.to_str().unwrap()])
        .output()
        .expect("executar alq inspect em PDF válido");
    assert_eq!(inspect_text_out.status.code(), Some(EXIT_SUCCESS));
    let stdout_text = String::from_utf8_lossy(&inspect_text_out.stdout);
    assert!(stdout_text.contains("Páginas: 1 (com texto: 1, sem texto: 0)"));
    assert!(stdout_text.contains("Título: Documento de Teste"));
    assert!(stdout_text.contains("Autor: Autor Teste"));
    assert!(stdout_text.contains("Idioma: pt-BR"));
    assert!(stdout_text.contains("Imagens: 0"));
    assert!(stdout_text.contains("Dimensões da página: 595.00 x 842.00 pt"));
    assert!(stdout_text.contains("Necessidade provável de OCR: Não"));

    let inspect_json_out = Command::new(bin)
        .args(["inspect", valid_pdf.to_str().unwrap(), "--json"])
        .output()
        .expect("executar alq inspect --json em PDF válido");
    assert_eq!(inspect_json_out.status.code(), Some(EXIT_SUCCESS));
    let stdout_json = String::from_utf8_lossy(&inspect_json_out.stdout);
    let parsed = parse_worker_response(&stdout_json).expect("JSON de inspect deve ser válido");
    let meta = parsed.metadata.expect("metadados presentes");
    assert_eq!(meta.title.as_deref(), Some("Documento de Teste"));
    assert_eq!(meta.author.as_deref(), Some("Autor Teste"));
    assert_eq!(meta.language.as_deref(), Some("pt-BR"));
    let stats = parsed.statistics.expect("estatísticas presentes");
    assert_eq!(stats.pages, 1);
    assert_eq!(stats.pages_with_text, 1);
    assert_eq!(stats.pages_without_text, 0);
    assert_eq!(stats.images, 0);
    assert!(!stats.needs_ocr);

    let corrupted_pdf = temp.path().join("corrompido.pdf");
    std::fs::write(&corrupted_pdf, b"%PDF-1.4\ncorrompido").expect("escrever PDF corrompido");

    let corrupted_out = Command::new(bin)
        .args(["inspect", corrupted_pdf.to_str().unwrap()])
        .output()
        .expect("executar alq inspect em PDF corrompido");
    assert_eq!(corrupted_out.status.code(), Some(EXIT_RUNTIME_ERROR));
    let corrupted_stderr = String::from_utf8_lossy(&corrupted_out.stderr);
    assert!(corrupted_stderr.contains("PDF_OPEN_FAILED"));
}
