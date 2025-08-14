mod config;
mod monitor;
mod scrapers;
mod telegram;
mod types;

use std::process;
use tracing::{error, info};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

use config::Config;
use monitor::FlatMonitor;

#[tokio::main]
async fn main() {
    // Initialize logging
    init_logging();

    info!("Starting Berlin Flat Bot (Rust version)");

    // Load configuration
    let config = match Config::load() {
        Ok(config) => {
            if let Err(e) = config.validate() {
                error!("Configuration validation failed: {}", e);
                process::exit(1);
            }
            config
        }
        Err(e) => {
            error!("Failed to load configuration: {}", e);
            process::exit(1);
        }
    };

    info!("Configuration loaded successfully");
    info!("Monitor interval: {} seconds", config.monitor_interval);

    // Create and start the monitor
    let monitor = match FlatMonitor::new(config) {
        Ok(monitor) => monitor,
        Err(e) => {
            error!("Failed to create flat monitor: {}", e);
            process::exit(1);
        }
    };

    // Handle shutdown gracefully
    let shutdown_result = tokio::select! {
        result = monitor.start() => {
            match result {
                Ok(_) => {
                    info!("Monitor stopped gracefully");
                    Ok(())
                }
                Err(e) => {
                    error!("Monitor stopped with error: {}", e);
                    Err(e)
                }
            }
        }
        _ = tokio::signal::ctrl_c() => {
            info!("Received Ctrl+C, shutting down gracefully...");
            Ok(())
        }
    };

    match shutdown_result {
        Ok(_) => {
            info!("Berlin Flat Bot stopped successfully");
        }
        Err(e) => {
            error!("Berlin Flat Bot stopped with error: {}", e);
            process::exit(1);
        }
    }
}

/// Initialize logging with structured output
fn init_logging() {
    // Set default log level if not specified
    if std::env::var("RUST_LOG").is_err() {
        std::env::set_var("RUST_LOG", "berlin_flat_bot=info,warn");
    }

    let fmt_layer = tracing_subscriber::fmt::layer()
        .with_target(true)
        .with_thread_ids(false)
        .with_file(false)
        .with_line_number(false)
        .compact();

    let filter_layer = tracing_subscriber::EnvFilter::from_default_env();

    tracing_subscriber::registry()
        .with(filter_layer)
        .with(fmt_layer)
        .init();
}
