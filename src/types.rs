use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use thiserror::Error;

/// Represents a flat/apartment listing
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Flat {
    /// Unique identifier for the flat
    pub id: String,
    /// Title/name of the flat listing
    pub title: String,
    /// Optional URL link to the flat details
    pub link: Option<String>,
    /// Additional details about the flat (rooms, size, price, etc.)
    pub details: HashMap<String, String>,
    /// Whether WBS (Wohnberechtigungsschein) is required
    pub wbs_required: bool,
    /// Source website name
    pub source: String,
}

impl Flat {
    /// Extract room count from flat details
    pub fn room_count(&self) -> Option<f32> {
        let room_fields = ["Zimmer", "Zimmeranzahl", "rooms"];

        for field in &room_fields {
            if let Some(value) = self.details.get(*field) {
                // Extract first number from string using regex-like logic
                let mut number_str = String::new();
                let mut found_digit = false;

                for ch in value.chars() {
                    if ch.is_ascii_digit()
                        || (ch == '.' && found_digit)
                        || (ch == ',' && found_digit)
                    {
                        if ch == ',' {
                            number_str.push('.');
                        } else {
                            number_str.push(ch);
                        }
                        found_digit = true;
                    } else if found_digit {
                        break;
                    }
                }

                if let Ok(count) = number_str.parse::<f32>() {
                    return Some(count);
                }
            }
        }
        None
    }

    /// Check if flat meets filtering criteria (2+ rooms, no WBS)
    pub fn meets_criteria(&self) -> bool {
        let room_count = self.room_count().unwrap_or(0.0);
        (room_count == 0.0 || room_count >= 2.0) && !self.wbs_required
    }
}

/// Custom error types for the application
#[derive(Error, Debug)]
pub enum BotError {
    #[error("Website unavailable: {message}")]
    WebsiteUnavailable { message: String },

    #[error("High traffic detected: {message}")]
    HighTraffic { message: String },

    #[error("HTTP request failed: {0}")]
    HttpRequest(#[from] reqwest::Error),

    #[error("HTML parsing failed: {message}")]
    Parsing { message: String },

    #[error("Telegram API error: {0}")]
    Telegram(#[from] teloxide::RequestError),

    #[error("Configuration error: {0}")]
    Config(#[from] config::ConfigError),

    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),

    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Generic error: {0}")]
    Generic(#[from] anyhow::Error),
}

/// Result type alias for the application
pub type BotResult<T> = Result<T, BotError>;

/// Website status information
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WebsiteStatus {
    pub name: String,
    pub status: String,
    pub last_checked: chrono::DateTime<chrono::Utc>,
    pub error_count: u32,
}

impl WebsiteStatus {
    pub fn new(name: String) -> Self {
        Self {
            name,
            status: "Not checked yet".to_string(),
            last_checked: chrono::Utc::now(),
            error_count: 0,
        }
    }

    pub fn update_success(&mut self) {
        self.status = "Available".to_string();
        self.last_checked = chrono::Utc::now();
        self.error_count = 0;
    }

    pub fn update_error(&mut self, error: &str) {
        self.status = error.to_string();
        self.last_checked = chrono::Utc::now();
        self.error_count += 1;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_room_count_extraction() {
        let mut flat = Flat {
            id: "test".to_string(),
            title: "Test Flat".to_string(),
            link: None,
            details: HashMap::new(),
            wbs_required: false,
            source: "Test".to_string(),
        };

        // Test various room count formats
        flat.details.insert("Zimmer".to_string(), "2".to_string());
        assert_eq!(flat.room_count(), Some(2.0));

        flat.details
            .insert("Zimmer".to_string(), "2,5 Zimmer".to_string());
        assert_eq!(flat.room_count(), Some(2.5));

        flat.details.insert("Zimmer".to_string(), "3.0".to_string());
        assert_eq!(flat.room_count(), Some(3.0));
    }

    #[test]
    fn test_meets_criteria() {
        let mut flat = Flat {
            id: "test".to_string(),
            title: "Test Flat".to_string(),
            link: None,
            details: HashMap::new(),
            wbs_required: false,
            source: "Test".to_string(),
        };

        // 2+ rooms, no WBS - should meet criteria
        flat.details.insert("Zimmer".to_string(), "2".to_string());
        assert!(flat.meets_criteria());

        // 1 room - should not meet criteria
        flat.details.insert("Zimmer".to_string(), "1".to_string());
        assert!(!flat.meets_criteria());

        // WBS required - should not meet criteria
        flat.details.insert("Zimmer".to_string(), "3".to_string());
        flat.wbs_required = true;
        assert!(!flat.meets_criteria());
    }
}
