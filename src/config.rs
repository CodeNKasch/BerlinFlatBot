use crate::types::BotResult;
use serde::{Deserialize, Serialize};
use std::env;
use std::time::Duration;

/// Application configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    /// Telegram bot token
    pub bot_token: String,
    /// Main chat ID for notifications
    pub chat_id: String,
    /// Private chat ID for error notifications
    pub private_chat_id: String,
    /// Monitor interval in seconds
    pub monitor_interval: u64,
    /// HTTP request timeout in seconds
    pub request_timeout: u64,
    /// Maximum number of retries for failed requests
    pub max_retries: u32,
    /// Base backoff time in seconds
    pub base_backoff: u64,
    /// Maximum backoff time in seconds
    pub max_backoff: u64,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            bot_token: String::new(),
            chat_id: String::new(),
            private_chat_id: String::new(),
            monitor_interval: 60,
            request_timeout: 30,
            max_retries: 3,
            base_backoff: 60,
            max_backoff: 3600,
        }
    }
}

impl Config {
    /// Load configuration from environment variables and config file
    pub fn load() -> BotResult<Self> {
        let mut settings = config::Config::builder();

        // Try to load from config.json first
        if std::path::Path::new("config.json").exists() {
            settings = settings.add_source(config::File::with_name("config"));
        }

        // Override with environment variables
        settings = settings
            .add_source(config::Environment::with_prefix("BOT"))
            .set_default("monitor_interval", 60)?
            .set_default("request_timeout", 30)?
            .set_default("max_retries", 3)?
            .set_default("base_backoff", 60)?
            .set_default("max_backoff", 3600)?;

        let config = settings.build()?;
        let mut app_config: Config = config.try_deserialize()?;

        // Validate required fields
        if app_config.bot_token.is_empty() {
            app_config.bot_token = env::var("BOT_TOKEN").map_err(|_| {
                crate::types::BotError::Config(config::ConfigError::Message(
                    "BOT_TOKEN is required".to_string(),
                ))
            })?;
        }

        if app_config.chat_id.is_empty() {
            app_config.chat_id = env::var("CHAT_ID").map_err(|_| {
                crate::types::BotError::Config(config::ConfigError::Message(
                    "CHAT_ID is required".to_string(),
                ))
            })?;
        }

        if app_config.private_chat_id.is_empty() {
            app_config.private_chat_id = env::var("PRIVATE_CHAT_ID").map_err(|_| {
                crate::types::BotError::Config(config::ConfigError::Message(
                    "PRIVATE_CHAT_ID is required".to_string(),
                ))
            })?;
        }

        Ok(app_config)
    }

    /// Get monitor interval as Duration
    pub fn monitor_interval_duration(&self) -> Duration {
        Duration::from_secs(self.monitor_interval)
    }

    /// Get request timeout as Duration
    pub fn request_timeout_duration(&self) -> Duration {
        Duration::from_secs(self.request_timeout)
    }

    /// Get base backoff as Duration
    pub fn base_backoff_duration(&self) -> Duration {
        Duration::from_secs(self.base_backoff)
    }

    /// Get max backoff as Duration
    pub fn max_backoff_duration(&self) -> Duration {
        Duration::from_secs(self.max_backoff)
    }

    /// Validate configuration
    pub fn validate(&self) -> BotResult<()> {
        if self.bot_token.is_empty() {
            return Err(crate::types::BotError::Config(
                config::ConfigError::Message("bot_token cannot be empty".to_string()),
            ));
        }

        if self.chat_id.is_empty() {
            return Err(crate::types::BotError::Config(
                config::ConfigError::Message("chat_id cannot be empty".to_string()),
            ));
        }

        if self.private_chat_id.is_empty() {
            return Err(crate::types::BotError::Config(
                config::ConfigError::Message("private_chat_id cannot be empty".to_string()),
            ));
        }

        if self.monitor_interval == 0 {
            return Err(crate::types::BotError::Config(
                config::ConfigError::Message("monitor_interval must be greater than 0".to_string()),
            ));
        }

        if self.request_timeout == 0 {
            return Err(crate::types::BotError::Config(
                config::ConfigError::Message("request_timeout must be greater than 0".to_string()),
            ));
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_validation() {
        let mut config = Config::default();

        // Should fail validation with empty required fields
        assert!(config.validate().is_err());

        // Fill required fields
        config.bot_token = "test_token".to_string();
        config.chat_id = "test_chat".to_string();
        config.private_chat_id = "test_private_chat".to_string();

        // Should pass validation
        assert!(config.validate().is_ok());

        // Should fail with zero monitor interval
        config.monitor_interval = 0;
        assert!(config.validate().is_err());
    }

    #[test]
    fn test_duration_conversions() {
        let config = Config {
            monitor_interval: 60,
            request_timeout: 30,
            base_backoff: 120,
            max_backoff: 3600,
            ..Default::default()
        };

        assert_eq!(config.monitor_interval_duration(), Duration::from_secs(60));
        assert_eq!(config.request_timeout_duration(), Duration::from_secs(30));
        assert_eq!(config.base_backoff_duration(), Duration::from_secs(120));
        assert_eq!(config.max_backoff_duration(), Duration::from_secs(3600));
    }
}
