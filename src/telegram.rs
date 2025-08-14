use std::collections::HashMap;
use teloxide::{prelude::*, types::ParseMode, utils::markdown};
use tracing::{error, info};

use crate::config::Config;
use crate::types::{BotResult, Flat, WebsiteStatus};

/// Telegram bot for sending flat notifications
pub struct TelegramBot {
    bot: Bot,
    config: Config,
}

impl TelegramBot {
    /// Create a new Telegram bot instance
    pub fn new(config: Config) -> Self {
        let bot = Bot::new(&config.bot_token);
        Self { bot, config }
    }

    /// Send welcome message when bot starts
    pub async fn send_welcome(&self) -> BotResult<()> {
        let message = format!(
            "🏠 *Flat Monitor Started*\n\n\
            I will notify you about new flats every {} seconds!\n\n\
            Available commands:\n\
            • /list \\[scraper\\] \\- Show all current flats\n\
            • /help \\- Show this help message\n\
            • /status \\- Show website status\n\
            • /test \\- Test all scrapers\n\
            • /clear \\- Clear the flat cache",
            self.config.monitor_interval
        );

        self.send_message(&self.config.chat_id, &message, true)
            .await?;
        info!("Welcome message sent to chat {}", self.config.chat_id);
        Ok(())
    }

    /// Send error notification to private chat
    pub async fn send_error_notification(&self, error_message: &str) -> BotResult<()> {
        let message = format!(
            "⚠️ *Error in Flat Monitor*\n\n{}",
            markdown::escape(error_message)
        );

        match self
            .send_message(&self.config.private_chat_id, &message, true)
            .await
        {
            Ok(_) => {
                info!(
                    "Error notification sent to private chat {}",
                    self.config.private_chat_id
                );
                Ok(())
            }
            Err(e) => {
                error!("Failed to send error notification: {}", e);
                Err(e)
            }
        }
    }

    /// Send flat notifications
    pub async fn send_flat_updates(&self, flats: &[Flat]) -> BotResult<()> {
        if flats.is_empty() {
            return Ok(());
        }

        info!("Sending {} flat updates", flats.len());

        for flat in flats {
            let message = self.format_flat_message(flat);
            if let Err(e) = self
                .send_message(&self.config.chat_id, &message, true)
                .await
            {
                error!("Failed to send flat update: {}", e);
                // Continue sending other flats even if one fails
            }

            // Small delay between messages to avoid rate limiting
            tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        }

        Ok(())
    }

    /// Send help message
    pub async fn send_help_message(&self, chat_id: &str) -> BotResult<()> {
        let message = "🏠 *Berlin Flat Monitor*\n\n\
            I monitor multiple housing websites for new flats and notify you when they appear\\.\n\n\
            *Commands:*\n\
            • /list \\[scraper\\] \\- Show latest flats \\(optionally filter by scraper\\)\n\
            • /help \\- Show this help\n\
            • /status \\- Show website status\n\
            • /test \\- Test all scrapers\n\
            • /clear \\- Clear the flat cache\n\n\
            *Available scrapers:*\n\
            • InBerlinWohnen\n\
            • Degewo\n\
            • Gesobau\n\
            • Gewobag\n\
            • Stadt und Land".to_string();

        self.send_message(chat_id, &message, true).await?;
        Ok(())
    }

    /// Send status message
    pub async fn send_status_message(
        &self,
        chat_id: &str,
        statuses: &HashMap<String, WebsiteStatus>,
    ) -> BotResult<()> {
        let mut message = "🌐 *Website Status*\n\n".to_string();

        for (name, status) in statuses {
            let status_lower = status.status.to_lowercase();
            let icon = if status_lower.contains("not checked yet") {
                "⏳"
            } else if status_lower.contains("unavailable")
                || status_lower.contains("error")
                || status_lower.contains("timeout")
            {
                "❌"
            } else if status_lower.contains("high traffic") {
                "🚧"
            } else {
                "✅"
            };

            message.push_str(&format!(
                "*{}*\n_{} {}_\n\n",
                markdown::escape(name),
                icon,
                markdown::escape(&status.status)
            ));
        }

        self.send_message(chat_id, &message, true).await?;
        Ok(())
    }

    /// Send list of flats
    pub async fn send_flat_list(
        &self,
        chat_id: &str,
        flats: &[Flat],
        scraper_filter: Option<&str>,
    ) -> BotResult<()> {
        let filtered_flats: Vec<&Flat> = if let Some(filter) = scraper_filter {
            flats
                .iter()
                .filter(|flat| flat.source.to_lowercase() == filter.to_lowercase())
                .collect()
        } else {
            flats.iter().collect()
        };

        if filtered_flats.is_empty() {
            let message = if let Some(filter) = scraper_filter {
                format!("No flats available from {}\\.", markdown::escape(filter))
            } else {
                "No flats available at the moment\\.".to_string()
            };
            self.send_message(chat_id, &message, true).await?;
            return Ok(());
        }

        let total_flats = filtered_flats.len();
        let display_flats = &filtered_flats[..std::cmp::min(5, total_flats)];

        // Send header
        let header = if let Some(filter) = scraper_filter {
            format!(
                "Found {} flats from {} \\(showing {}\\):",
                total_flats,
                markdown::escape(filter),
                display_flats.len()
            )
        } else {
            format!(
                "Found {} flats \\(showing {}\\):",
                total_flats,
                display_flats.len()
            )
        };

        self.send_message(chat_id, &header, true).await?;

        // Send individual flats
        for flat in display_flats {
            let message = self.format_flat_message(flat);
            self.send_message(chat_id, &message, true).await?;

            // Small delay between messages
            tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        }

        Ok(())
    }

    /// Send test results
    pub async fn send_test_results(
        &self,
        chat_id: &str,
        results: &[(String, Result<Option<Flat>, String>)],
    ) -> BotResult<()> {
        let mut message = "🏠 *Test Results*\n\n".to_string();

        for (scraper_name, result) in results {
            message.push_str(&format!("*{}*\n", markdown::escape(scraper_name)));

            match result {
                Ok(Some(flat)) => {
                    let title = markdown::escape(&flat.title);
                    if let Some(link) = &flat.link {
                        message.push_str(&format!("[{}]({})\n\n", title, link));
                    } else {
                        message.push_str(&format!("{}\n\n", title));
                    }
                }
                Ok(None) => {
                    message.push_str("_No flats found_\n\n");
                }
                Err(error) => {
                    message.push_str(&format!("_Error: {}_\n\n", markdown::escape(error)));
                }
            }
        }

        self.send_message(chat_id, &message, true).await?;
        Ok(())
    }

    /// Send clear confirmation
    pub async fn send_clear_confirmation(&self, chat_id: &str) -> BotResult<()> {
        self.send_message(chat_id, "✅ Flat cache cleared successfully!", false)
            .await?;
        Ok(())
    }

    /// Format a flat as a Telegram message
    fn format_flat_message(&self, flat: &Flat) -> String {
        let icon = if flat.wbs_required { "🏠" } else { "✅" };

        let mut message = if let Some(link) = &flat.link {
            format!("{} [{}]({})\n", icon, markdown::escape(&flat.title), link)
        } else {
            format!("{} {}\n", icon, markdown::escape(&flat.title))
        };

        // Add details
        for (key, value) in &flat.details {
            if !value.trim().is_empty() {
                message.push_str(&format!(
                    "• {}: {}\n",
                    markdown::escape(key),
                    markdown::escape(value)
                ));
            }
        }

        // Add source
        if let Some(link) = &flat.link {
            message.push_str(&format!("[{}]({})\n", markdown::escape(&flat.source), link));
        } else {
            message.push_str(&format!("{}\n", markdown::escape(&flat.source)));
        }

        message
    }

    /// Send a message with proper error handling
    async fn send_message(&self, chat_id: &str, text: &str, use_markdown: bool) -> BotResult<()> {
        let chat_id_num = chat_id.parse::<i64>().map_err(|_| {
            crate::types::BotError::Config(config::ConfigError::Message(format!(
                "Invalid chat ID: {}",
                chat_id
            )))
        })?;

        let mut request = self
            .bot
            .send_message(teloxide::types::ChatId(chat_id_num), text);

        if use_markdown {
            request = request.parse_mode(ParseMode::MarkdownV2);
        }

        request = request.disable_web_page_preview(true);

        match request.await {
            Ok(_) => Ok(()),
            Err(e) => {
                error!("Failed to send message to {}: {}", chat_id_num, e);
                Err(crate::types::BotError::Telegram(e))
            }
        }
    }
}


#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

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
    fn test_flat_message_formatting() {
        let config = create_test_config();
        let telegram = TelegramBot::new(config);

        let mut details = HashMap::new();
        details.insert("Zimmer".to_string(), "2".to_string());
        details.insert("Preis".to_string(), "800€".to_string());

        let flat = Flat {
            id: "test_id".to_string(),
            title: "Test Wohnung".to_string(),
            link: Some("https://example.com".to_string()),
            details,
            wbs_required: false,
            source: "Test".to_string(),
        };

        let message = telegram.format_flat_message(&flat);

        assert!(message.contains("✅"));
        assert!(message.contains("Test Wohnung"));
        assert!(message.contains("Zimmer: 2"));
        assert!(message.contains("Preis: 800€"));
        assert!(message.contains("https://example.com"));
    }

    #[test]
    fn test_telegram_bot_creation() {
        let config = create_test_config();
        let telegram = TelegramBot::new(config.clone());

        assert_eq!(telegram.config.bot_token, config.bot_token);
        assert_eq!(telegram.config.chat_id, config.chat_id);
    }
}
