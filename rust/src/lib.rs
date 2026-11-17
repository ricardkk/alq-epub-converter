//! Biblioteca principal do orquestrador CLI `alq` (`alq-epub-converter`).
//!
//! Expõe os módulos de interface de linha de comando, configuração, protocolo JSON v1,
//! execução de subprocesso Python, progresso no terminal e tratamento de erros.

pub mod cli;
pub mod commands;
pub mod config;
pub mod error;
pub mod progress;
pub mod protocol;
pub mod runner;
