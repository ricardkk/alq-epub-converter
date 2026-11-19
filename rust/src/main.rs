use std::process;

use clap::Parser;

use alq::cli::Cli;
use alq::commands::execute;
use alq::error::{EXIT_SUCCESS, EXIT_VALIDATION_ERROR};

fn main() {
    let cli = match Cli::try_parse() {
        Ok(cli) => cli,
        Err(err) => {
            let _ = err.print();
            let code = if err.use_stderr() {
                EXIT_VALIDATION_ERROR
            } else {
                EXIT_SUCCESS
            };
            process::exit(code);
        }
    };

    match execute(&cli) {
        Ok(_) => process::exit(EXIT_SUCCESS),
        Err(err) => {
            eprintln!("Erro: {err}");
            process::exit(err.exit_code());
        }
    }
}
