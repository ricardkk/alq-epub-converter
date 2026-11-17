//! Parsing de eventos `STAGE:<atual>/<total>:<mensagem>`, logging técnico (`tracing_subscriber`)
//! e renderização de progresso no terminal via `indicatif`.

use indicatif::{ProgressBar, ProgressDrawTarget, ProgressStyle};
use tracing_subscriber::EnvFilter;

/// Variável de ambiente para habilitar logs de depuração no `alq`.
pub const ENV_ALQ_DEBUG: &str = "ALQ_DEBUG";

/// Variável de ambiente de fallback para habilitar logs de depuração.
pub const ENV_PDF2EPUB_DEBUG: &str = "PDF2EPUB_DEBUG";

/// Evento estruturado de progresso emitido pelo worker Python no `stderr`.
///
/// Formato esperado: `STAGE:<atual>/<total>:<mensagem>` (ex.: `STAGE:1/6:Inspecionando PDF`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StageEvent {
    /// Índice da etapa atual (`1..=total`).
    pub current: u64,
    /// Total de etapas previstas no pipeline.
    pub total: u64,
    /// Descrição legível da etapa em execução.
    pub message: String,
}

impl StageEvent {
    /// Formata a etapa de modo legível (ex.: `[1/6] Inspecionando PDF`).
    #[must_use]
    pub fn format_step(&self) -> String {
        format!("[{}/{}] {}", self.current, self.total, self.message)
    }
}

/// Verifica se uma string de variável de ambiente representa valor verdadeiro (`1`, `true`, `yes`, `debug`).
#[must_use]
pub fn is_truthy_env_value(val: &str) -> bool {
    matches!(
        val.trim().to_ascii_lowercase().as_str(),
        "1" | "true" | "yes" | "on" | "debug"
    )
}

/// Determina se o modo de depuração está ativo via flag `--debug` ou variáveis `ALQ_DEBUG` / `PDF2EPUB_DEBUG`.
#[must_use]
pub fn is_debug_enabled(cli_debug: bool) -> bool {
    if cli_debug {
        return true;
    }

    if let Ok(val) = std::env::var(ENV_ALQ_DEBUG) {
        if is_truthy_env_value(&val) {
            return true;
        }
    }

    if let Ok(val) = std::env::var(ENV_PDF2EPUB_DEBUG) {
        if is_truthy_env_value(&val) {
            return true;
        }
    }

    false
}

/// Inicializa o subscriber global `tracing_subscriber` direcionando diagnósticos para o `stderr`.
///
/// Se um subscriber global já estiver registrado no processo (ex.: em múltiplos testes),
/// a chamada é ignorada silenciosamente.
pub fn init_logging(cli_debug: bool) {
    let default_directive = if is_debug_enabled(cli_debug) {
        "debug"
    } else {
        "warn"
    };

    let filter =
        EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new(default_directive));

    let _ = tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_writer(std::io::stderr)
        .with_target(false)
        .without_time()
        .try_init();
}

/// Analisa uma linha do `stderr` do worker Python e extrai um [`StageEvent`] se possuir o prefixo `STAGE:`.
///
/// Suporta o formato canônico `STAGE:<atual>/<total>:<mensagem>`.
#[must_use]
pub fn parse_stage_line(line: &str) -> Option<StageEvent> {
    let trimmed = line.trim();
    let rest = trimmed.strip_prefix("STAGE:")?;
    let (counts_part, message_part) = rest.split_once(':')?;
    let message = message_part.trim();
    if message.is_empty() {
        return None;
    }

    let (current_str, total_str) = counts_part.split_once('/')?;
    let current = current_str.trim().parse::<u64>().ok()?;
    let total = total_str.trim().parse::<u64>().ok()?;

    if current == 0 || total == 0 || current > total {
        return None;
    }

    Some(StageEvent {
        current,
        total,
        message: message.to_string(),
    })
}

/// Gerenciador de progresso e consumo de linhas `stderr` do subprocesso Python.
#[derive(Debug)]
pub struct ProgressReporter {
    bar: ProgressBar,
    stages: Vec<StageEvent>,
}

impl ProgressReporter {
    /// Cria um novo [`ProgressReporter`].
    ///
    /// Quando `show_bar` é `true`, exibe indicador de progresso via `indicatif` no `stderr`.
    /// Quando `false`, mantém uma barra oculta (`ProgressBar::hidden()`) apenas coletando eventos.
    #[must_use]
    pub fn new(show_bar: bool) -> Self {
        let bar = if show_bar {
            let pb = ProgressBar::with_draw_target(Some(1), ProgressDrawTarget::stderr());
            if let Ok(style) = ProgressStyle::with_template("[{pos}/{len}] {wide_msg}")
                .map(|s| s.tick_chars("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"))
            {
                pb.set_style(style);
            }
            pb
        } else {
            ProgressBar::hidden()
        };

        Self {
            bar,
            stages: Vec::new(),
        }
    }

    /// Processa uma linha recebida do `stderr` do worker Python.
    ///
    /// - Linhas `STAGE:<atual>/<total>:<mensagem>` atualizam a barra `indicatif` e são armazenadas.
    /// - Demais linhas não vazias são enviadas para `tracing::debug!`.
    pub fn handle_stderr_line(&mut self, line: &str) {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            return;
        }

        if let Some(stage) = parse_stage_line(trimmed) {
            tracing::debug!(
                current = stage.current,
                total = stage.total,
                "Etapa de progresso: {}",
                stage.message
            );
            self.bar.set_length(stage.total);
            self.bar.set_position(stage.current);
            self.bar.set_message(stage.message.clone());
            self.stages.push(stage);
        } else {
            tracing::debug!(target: "alq::python", "{trimmed}");
        }
    }

    /// Finaliza e limpa a barra de progresso no terminal.
    pub fn finish(&self) {
        self.bar.finish_and_clear();
    }

    /// Retorna as etapas `STAGE:` registradas até o momento.
    #[must_use]
    pub fn stages(&self) -> &[StageEvent] {
        &self.stages
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_valid_stage_lines() {
        let ev = parse_stage_line("STAGE:1/6:Inspecionando arquivo PDF").expect("deve fazer parse");
        assert_eq!(
            ev,
            StageEvent {
                current: 1,
                total: 6,
                message: "Inspecionando arquivo PDF".to_string(),
            }
        );
        assert_eq!(ev.format_step(), "[1/6] Inspecionando arquivo PDF");

        let ev_spaces = parse_stage_line("  STAGE: 3 / 6 : Extraindo capítulos e TOC  ")
            .expect("parse com espaços");
        assert_eq!(ev_spaces.current, 3);
        assert_eq!(ev_spaces.total, 6);
        assert_eq!(ev_spaces.message, "Extraindo capítulos e TOC");
    }

    #[test]
    fn rejects_invalid_stage_lines() {
        assert!(parse_stage_line("DEBUG: abrindo arquivo").is_none());
        assert!(parse_stage_line("STAGE:0/6:Etapa zero inválida").is_none());
        assert!(parse_stage_line("STAGE:7/6:Acima do total").is_none());
        assert!(parse_stage_line("STAGE:1/0:Total zero").is_none());
        assert!(parse_stage_line("STAGE:1/6:   ").is_none());
        assert!(parse_stage_line("STAGE:invalido:mensagem").is_none());
    }

    #[test]
    fn reporter_collects_stages_and_ignores_regular_debug_lines() {
        init_logging(false);
        let mut reporter = ProgressReporter::new(false);
        reporter.handle_stderr_line("DEBUG: Iniciando worker Python");
        reporter.handle_stderr_line("STAGE:1/2:Carregando documento");
        reporter.handle_stderr_line("STAGE:2/2:Gerando EPUB");
        reporter.finish();

        assert_eq!(reporter.stages().len(), 2);
        assert_eq!(reporter.stages()[0].current, 1);
        assert_eq!(reporter.stages()[1].current, 2);
    }

    #[test]
    fn truthy_env_values_are_recognized() {
        assert!(is_truthy_env_value("1"));
        assert!(is_truthy_env_value("true"));
        assert!(is_truthy_env_value("TRUE"));
        assert!(is_truthy_env_value("debug"));
        assert!(!is_truthy_env_value("0"));
        assert!(!is_truthy_env_value("false"));
        assert!(!is_truthy_env_value(""));
    }
}
