use dashmap::DashMap;
use reqwest::Client;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use teloxide::{prelude::*, utils::command::BotCommands};
use tokio::sync::RwLock;
use tracing::{error, info, warn};

use crate::config::Config;
use crate::scrapers::{create_client, create_scrapers, Scraper};
use crate::telegram::TelegramBot;
use crate::types::{BotResult, Flat};

/// Context for command handling
struct CommandContext {
    telegram: Arc<TelegramBot>,
    current_flats: Arc<RwLock<Vec<Flat>>>,
    seen_flat_ids: Arc<DashMap<String, ()>>,
    config: Config,
    client: Client,
}

/// Bot commands enum
#[derive(BotCommands, Clone)]
#[command(
    rename_rule = "lowercase",
    description = "Berlin Flat Monitor commands:"
)]
pub enum Command {
    #[command(description = "Show this help message")]
    Help,
    #[command(description = "Show current available flats")]
    List,
    #[command(description = "Show website status")]
    Status,
    #[command(description = "Test all scrapers and show results")]
    Test,
    #[command(description = "Clear the flat cache")]
    Clear,
}

/// Main monitoring application
pub struct FlatMonitor {
    config: Config,
    scrapers: Vec<Box<dyn Scraper>>,
    telegram: Arc<TelegramBot>,
    client: Client,
    current_flats: Arc<RwLock<Vec<Flat>>>,
    seen_flat_ids: Arc<DashMap<String, ()>>,
}

impl FlatMonitor {
    /// Create a new flat monitor instance
    pub fn new(config: Config) -> BotResult<Self> {
        let scrapers = create_scrapers(config.clone());
        let telegram = Arc::new(TelegramBot::new(config.clone()));
        let client = create_client(&config)?;

        Ok(Self {
            config,
            scrapers,
            telegram,
            client,
            current_flats: Arc::new(RwLock::new(Vec::new())),
            seen_flat_ids: Arc::new(DashMap::new()),
        })
    }

    /// Start the monitoring process
    pub async fn start(&self) -> BotResult<()> {
        info!("Starting Berlin Flat Monitor");

        // Send welcome message
        self.telegram.send_welcome().await?;

        // Initialize with current flats
        match self.fetch_all_flats().await {
            Ok(flats) => {
                info!("Initialized with {} existing flats", flats.len());
                let mut current_flats = self.current_flats.write().await;
                *current_flats = flats;
            }
            Err(e) => {
                let error_msg = format!("Failed to initialize flats: {}", e);
                error!("{}", error_msg);
                self.telegram.send_error_notification(&error_msg).await?;
            }
        }

        // Start command handler
        let telegram_clone = Arc::clone(&self.telegram);
        let current_flats_clone = Arc::clone(&self.current_flats);
        let seen_flat_ids_clone = Arc::clone(&self.seen_flat_ids);
        let config_clone = self.config.clone();
        let client_clone = self.client.clone();

        let bot = Bot::new(&self.config.bot_token);
        let handler = move |bot: Bot, msg: Message, cmd: Command| {
            let context = CommandContext {
                telegram: Arc::clone(&telegram_clone),
                current_flats: Arc::clone(&current_flats_clone),
                seen_flat_ids: Arc::clone(&seen_flat_ids_clone),
                config: config_clone.clone(),
                client: client_clone.clone(),
            };

            async move {
                Self::handle_command(bot, msg, cmd, context).await
            }
        };

        // Start command dispatcher in background
        let mut dispatcher = Dispatcher::builder(
            bot,
            Update::filter_message()
                .filter_command::<Command>()
                .endpoint(handler),
        )
        .enable_ctrlc_handler()
        .build();

        tokio::spawn(async move {
            dispatcher.dispatch().await;
        });

        // Start monitoring loop
        self.monitoring_loop().await
    }

    /// Main monitoring loop
    async fn monitoring_loop(&self) -> BotResult<()> {
        let mut interval = tokio::time::interval(self.config.monitor_interval_duration());

        loop {
            interval.tick().await;

            if let Err(e) = self.check_for_new_flats().await {
                let error_msg = format!("Error during monitoring: {}", e);
                error!("{}", error_msg);
                if let Err(notification_err) =
                    self.telegram.send_error_notification(&error_msg).await
                {
                    error!("Failed to send error notification: {}", notification_err);
                }
            }
        }
    }

    /// Check for new flats and send notifications
    async fn check_for_new_flats(&self) -> BotResult<()> {
        info!("Checking for new flats...");

        let new_flats = self.fetch_all_flats().await?;

        // Find flats that weren't seen before
        let current_flats = self.current_flats.read().await;
        let current_ids: HashSet<String> = current_flats.iter().map(|f| f.id.clone()).collect();
        drop(current_flats);

        let truly_new_flats: Vec<Flat> = new_flats
            .iter()
            .filter(|flat| !current_ids.contains(&flat.id))
            .filter(|flat| !self.seen_flat_ids.contains_key(&flat.id))
            .cloned()
            .collect();

        if !truly_new_flats.is_empty() {
            info!("Found {} new flats", truly_new_flats.len());

            // Filter for flats with 2+ rooms and no WBS
            let filtered_flats: Vec<Flat> = truly_new_flats
                .into_iter()
                .filter(|flat| flat.meets_criteria())
                .collect();

            if !filtered_flats.is_empty() {
                info!("Found {} new flats matching criteria", filtered_flats.len());

                // Mark as seen
                for flat in &filtered_flats {
                    self.seen_flat_ids.insert(flat.id.clone(), ());
                }

                // Send notifications
                self.telegram.send_flat_updates(&filtered_flats).await?;
            }
        }

        // Update current flats cache
        let mut current_flats = self.current_flats.write().await;
        *current_flats = new_flats;

        Ok(())
    }

    /// Fetch flats from all scrapers
    async fn fetch_all_flats(&self) -> BotResult<Vec<Flat>> {
        let mut all_flats = Vec::new();

        for scraper in &self.scrapers {
            if scraper.should_backoff() {
                warn!("Skipping {} due to backoff", scraper.name());
                continue;
            }

            match scraper.fetch_flats(&self.client).await {
                Ok(flats) => {
                    info!("Fetched {} flats from {}", flats.len(), scraper.name());
                    all_flats.extend(flats);
                    scraper.update_success();
                }
                Err(e) => {
                    let error_msg = format!("Failed to fetch from {}: {}", scraper.name(), e);
                    error!("{}", error_msg);
                    scraper.update_error(&error_msg);
                }
            }
        }

        Ok(all_flats)
    }


    /// Handle bot commands
    async fn handle_command(
        _bot: Bot,
        msg: Message,
        cmd: Command,
        context: CommandContext,
    ) -> ResponseResult<()> {
        let chat_id = msg.chat.id.to_string();

        // Only respond to configured chat
        if chat_id != context.config.chat_id {
            return Ok(());
        }

        match cmd {
            Command::Help => {
                if let Err(e) = context.telegram.send_help_message(&chat_id).await {
                    error!("Failed to send help message: {}", e);
                }
            }
            Command::List => {
                let flats = context.current_flats.read().await;
                if let Err(e) = context.telegram.send_flat_list(&chat_id, &flats, None).await {
                    error!("Failed to send flat list: {}", e);
                }
            }
            Command::Status => {
                // Create scrapers to get current status
                let scrapers = create_scrapers(context.config.clone());
                let mut statuses = HashMap::new();

                for scraper in scrapers {
                    statuses.insert(scraper.name().to_string(), scraper.status());
                }

                if let Err(e) = context.telegram.send_status_message(&chat_id, &statuses).await {
                    error!("Failed to send status message: {}", e);
                }
            }
            Command::Test => {
                let scrapers = create_scrapers(context.config.clone());
                let mut results = Vec::new();

                // Clear seen flats for testing
                context.seen_flat_ids.clear();

                for scraper in scrapers {
                    let result = match scraper.fetch_flats(&context.client).await {
                        Ok(flats) => {
                            if let Some(first_flat) = flats.into_iter().next() {
                                Ok(Some(first_flat))
                            } else {
                                Ok(None)
                            }
                        }
                        Err(e) => Err(e.to_string()),
                    };

                    results.push((scraper.name().to_string(), result));
                }

                if let Err(e) = context.telegram.send_test_results(&chat_id, &results).await {
                    error!("Failed to send test results: {}", e);
                }
            }
            Command::Clear => {
                // Clear current flats cache
                let mut flats = context.current_flats.write().await;
                flats.clear();

                // Clear seen IDs
                context.seen_flat_ids.clear();

                if let Err(e) = context.telegram.send_clear_confirmation(&chat_id).await {
                    error!("Failed to send clear confirmation: {}", e);
                }
            }
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn create_test_config() -> Config {
        Config {
            bot_token: "test_token".to_string(),
            chat_id: "123456789".to_string(),
            private_chat_id: "987654321".to_string(),
            monitor_interval: 60,
            request_timeout: 30,
            max_retries: 3,
            base_backoff: 60,
            max_backoff: 3600,
        }
    }

    #[test]
    fn test_monitor_creation() {
        let config = create_test_config();
        let monitor = FlatMonitor::new(config);

        assert!(monitor.is_ok());
    }

    #[tokio::test]
    async fn test_flat_filtering() {
        let config = create_test_config();
        let _monitor = FlatMonitor::new(config).unwrap();

        let mut details = HashMap::new();
        details.insert("Zimmer".to_string(), "2".to_string());

        let flat = Flat {
            id: "test_id".to_string(),
            title: "Test Flat".to_string(),
            link: None,
            details,
            wbs_required: false,
            source: "Test".to_string(),
        };

        assert!(flat.meets_criteria());
    }
}
