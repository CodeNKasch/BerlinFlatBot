use async_trait::async_trait;
use reqwest::Client;
use scraper::{Html, Selector};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tracing::{debug, info};

use crate::config::Config;
use crate::types::{BotError, BotResult, Flat, WebsiteStatus};

/// Trait for website scrapers
#[async_trait]
pub trait Scraper: Send + Sync {
    /// Get the name of the scraper
    fn name(&self) -> &str;


    /// Fetch flats from the website
    async fn fetch_flats(&self, client: &Client) -> BotResult<Vec<Flat>>;

    /// Get current status
    fn status(&self) -> WebsiteStatus;

    /// Update status after successful fetch
    fn update_success(&self);

    /// Update status after error
    fn update_error(&self, error: &str);

    /// Check if scraper should be backed off
    fn should_backoff(&self) -> bool;
}

/// Base scraper implementation with common functionality
pub struct BaseScraper {
    name: String,
    url: String,
    status: Arc<std::sync::Mutex<WebsiteStatus>>,
    last_error: Arc<std::sync::Mutex<Option<Instant>>>,
    backoff_duration: Arc<std::sync::Mutex<Duration>>,
    config: Config,
}

impl BaseScraper {
    pub fn new(name: String, url: String, config: Config) -> Self {
        Self {
            status: Arc::new(std::sync::Mutex::new(WebsiteStatus::new(name.clone()))),
            name,
            url,
            last_error: Arc::new(std::sync::Mutex::new(None)),
            backoff_duration: Arc::new(std::sync::Mutex::new(config.base_backoff_duration())),
            config,
        }
    }

    /// Make HTTP request with retry logic
    async fn make_request(
        &self,
        client: &Client,
        method: reqwest::Method,
        url: &str,
    ) -> BotResult<String> {
        let mut last_error = None;

        for attempt in 1..=self.config.max_retries {
            debug!("Attempt {} for {}", attempt, url);

            match client
                .request(method.clone(), url)
                .timeout(self.config.request_timeout_duration())
                .send()
                .await
            {
                Ok(response) => match response.status().as_u16() {
                    200 => {
                        let text = response.text().await?;
                        self.reset_backoff();
                        return Ok(text);
                    }
                    429 | 503 => {
                        let error = BotError::HighTraffic {
                            message: format!("Server returned status {}", response.status()),
                        };
                        self.update_backoff();
                        return Err(error);
                    }
                    status => {
                        let error = BotError::WebsiteUnavailable {
                            message: format!("Server returned status {}", status),
                        };
                        last_error = Some(error);
                    }
                },
                Err(e) => {
                    if e.is_timeout() {
                        last_error = Some(BotError::WebsiteUnavailable {
                            message: "Request timeout".to_string(),
                        });
                    } else {
                        last_error = Some(BotError::HttpRequest(e));
                    }
                }
            }

            if attempt < self.config.max_retries {
                let delay = Duration::from_secs(2_u64.pow(attempt - 1));
                debug!("Retrying in {:?}", delay);
                tokio::time::sleep(delay).await;
            }
        }

        self.update_backoff();
        Err(last_error.unwrap_or(BotError::WebsiteUnavailable {
            message: "Max retries exceeded".to_string(),
        }))
    }

    fn update_backoff(&self) {
        if let Ok(mut last_error) = self.last_error.lock() {
            *last_error = Some(Instant::now());
        }

        if let Ok(mut backoff) = self.backoff_duration.lock() {
            *backoff = std::cmp::min(*backoff * 2, self.config.max_backoff_duration());
        }
    }

    fn reset_backoff(&self) {
        if let Ok(mut last_error) = self.last_error.lock() {
            *last_error = None;
        }

        if let Ok(mut backoff) = self.backoff_duration.lock() {
            *backoff = self.config.base_backoff_duration();
        }
    }
}

/// InBerlinWohnen scraper
pub struct InBerlinWohnenScraper {
    base: BaseScraper,
}

impl InBerlinWohnenScraper {
    pub fn new(config: Config) -> Self {
        Self {
            base: BaseScraper::new(
                "InBerlinWohnen".to_string(),
                "https://inberlinwohnen.de/wohnungsfinder/".to_string(),
                config,
            ),
        }
    }

    fn parse_flat(&self, element: &scraper::ElementRef) -> Option<Flat> {
        let id = element.value().id().unwrap_or("").to_string();
        if id.is_empty() || !id.starts_with("flat_") {
            return None;
        }

        // Extract title
        let title_selector = Selector::parse("h2").ok()?;
        let title = element
            .select(&title_selector)
            .next()?
            .text()
            .collect::<String>()
            .trim()
            .to_string();

        // Extract link
        let link_selector = Selector::parse("a.org-but").ok()?;
        let link = element
            .select(&link_selector)
            .next()
            .and_then(|a| a.value().attr("href"))
            .map(|href| {
                if href.starts_with("http") {
                    href.to_string()
                } else {
                    format!("https://inberlinwohnen.de{}", href)
                }
            });

        // Extract details from tables
        let mut details = HashMap::new();
        let table_selector = Selector::parse("table.tb-small-data").ok()?;
        let row_selector = Selector::parse("tr").ok()?;
        let th_selector = Selector::parse("th").ok()?;
        let td_selector = Selector::parse("td").ok()?;

        for table in element.select(&table_selector) {
            for row in table.select(&row_selector) {
                if let (Some(th), Some(td)) = (
                    row.select(&th_selector).next(),
                    row.select(&td_selector).next(),
                ) {
                    let key = th
                        .text()
                        .collect::<String>()
                        .trim()
                        .trim_end_matches(':')
                        .to_string();
                    let value = td.text().collect::<String>().trim().to_string();
                    if !key.is_empty() && !value.is_empty() {
                        details.insert(key, value);
                    }
                }
            }
        }

        // Extract features
        let feature_selector = Selector::parse("span.hackerl").ok()?;
        let features: Vec<String> = element
            .select(&feature_selector)
            .map(|span| span.text().collect::<String>().trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();

        if !features.is_empty() {
            details.insert("Features".to_string(), features.join(", "));
        }

        // Check for WBS requirement
        let wbs_required = details
            .get("WBS")
            .map(|wbs| {
                wbs.to_lowercase().contains("erforderlich") || wbs.to_lowercase().contains("wbs")
            })
            .unwrap_or(false);

        Some(Flat {
            id,
            title,
            link,
            details,
            wbs_required,
            source: "InBerlinWohnen".to_string(),
        })
    }
}

#[async_trait]
impl Scraper for InBerlinWohnenScraper {
    fn name(&self) -> &str {
        &self.base.name
    }

    async fn fetch_flats(&self, client: &Client) -> BotResult<Vec<Flat>> {
        info!("Fetching flats from {}", self.name());

        let html = self
            .base
            .make_request(client, reqwest::Method::GET, &self.base.url)
            .await?;
        let document = Html::parse_document(&html);

        // Check for high traffic message
        if html.to_lowercase().contains("high traffic") {
            return Err(BotError::HighTraffic {
                message: "Website experiencing high traffic".to_string(),
            });
        }

        let flat_selector = Selector::parse("li[id^='flat_']").map_err(|e| BotError::Parsing {
            message: format!("Invalid CSS selector: {}", e),
        })?;

        let flats: Vec<Flat> = document
            .select(&flat_selector)
            .filter_map(|element| self.parse_flat(&element))
            .collect();

        info!("Found {} flats from {}", flats.len(), self.name());
        self.update_success();
        Ok(flats)
    }

    fn status(&self) -> WebsiteStatus {
        self.base.status.lock().unwrap().clone()
    }

    fn update_success(&self) {
        if let Ok(mut status) = self.base.status.lock() {
            status.update_success();
        }
    }

    fn update_error(&self, error: &str) {
        if let Ok(mut status) = self.base.status.lock() {
            status.update_error(error);
        }
    }

    fn should_backoff(&self) -> bool {
        if let (Ok(last_error), Ok(backoff)) = (
            self.base.last_error.lock(),
            self.base.backoff_duration.lock(),
        ) {
            if let Some(last_error_time) = *last_error {
                return last_error_time.elapsed() < *backoff;
            }
        }
        false
    }
}

/// Degewo scraper
pub struct DegewoScraper {
    base: BaseScraper,
}

impl DegewoScraper {
    pub fn new(config: Config) -> Self {
        Self {
            base: BaseScraper::new(
                "Degewo".to_string(),
                "https://www.degewo.de/immosuche".to_string(),
                config,
            ),
        }
    }

    fn parse_flat(&self, element: &scraper::ElementRef) -> Option<Flat> {
        // Extract ID from the article's ID attribute
        let id = element
            .value()
            .attr("id")?
            .strip_prefix("immobilie-list-item-")?
            .to_string();

        // Extract title
        let title_selector = Selector::parse("h2.article__title").ok()?;
        let title = element
            .select(&title_selector)
            .next()?
            .text()
            .collect::<String>()
            .trim()
            .to_string();

        // Extract link
        let link_selector = Selector::parse("a[href]").ok()?;
        let link = element
            .select(&link_selector)
            .next()
            .and_then(|a| a.value().attr("href"))
            .map(|href| {
                if href.starts_with("http") {
                    href.to_string()
                } else {
                    format!("https://www.degewo.de{}", href)
                }
            });

        let mut details = HashMap::new();

        // Extract address
        let address_selector = Selector::parse("span.article__meta").ok()?;
        if let Some(address) = element.select(&address_selector).next() {
            details.insert(
                "Adresse".to_string(),
                address.text().collect::<String>().trim().to_string(),
            );
        }

        // Extract tags
        let tags_selector = Selector::parse("li.article__tags-item").ok()?;
        let tags: Vec<String> = element
            .select(&tags_selector)
            .map(|tag| tag.text().collect::<String>().trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();

        if !tags.is_empty() {
            details.insert("Tags".to_string(), tags.join(", "));
        }

        // Extract properties (rooms, size, availability)
        let properties_selector = Selector::parse("li.article__properties-item").ok()?;
        for prop in element.select(&properties_selector) {
            let svg_selector = Selector::parse("svg").ok()?;
            let text_selector = Selector::parse("span.text").ok()?;

            if let (Some(svg), Some(text)) = (
                prop.select(&svg_selector).next(),
                prop.select(&text_selector).next(),
            ) {
                let href = svg.value().attr("xlink:href").unwrap_or("");
                let text_content = text.text().collect::<String>().trim().to_string();

                if href.contains("i-room") {
                    details.insert("Zimmeranzahl".to_string(), text_content);
                } else if href.contains("i-squares") {
                    details.insert("Wohnfläche".to_string(), text_content);
                } else if href.contains("i-calendar2") {
                    details.insert("Verfügbarkeit".to_string(), text_content);
                }
            }
        }

        // Extract price
        let price_selector = Selector::parse("div.article__price-tag span.price").ok()?;
        if let Some(price) = element.select(&price_selector).next() {
            details.insert(
                "Warmmiete".to_string(),
                price.text().collect::<String>().trim().to_string(),
            );
        }

        // Check for WBS requirement
        let wbs_required = title.to_uppercase().contains("WBS");

        Some(Flat {
            id,
            title,
            link,
            details,
            wbs_required,
            source: "Degewo".to_string(),
        })
    }
}

#[async_trait]
impl Scraper for DegewoScraper {
    fn name(&self) -> &str {
        &self.base.name
    }

    async fn fetch_flats(&self, client: &Client) -> BotResult<Vec<Flat>> {
        info!("Fetching flats from {}", self.name());

        let html = self
            .base
            .make_request(client, reqwest::Method::GET, &self.base.url)
            .await?;
        let document = Html::parse_document(&html);

        let flat_selector = Selector::parse(
            "article.article-list__item.article-list__item--immosearch",
        )
        .map_err(|e| BotError::Parsing {
            message: format!("Invalid CSS selector: {}", e),
        })?;

        let flats: Vec<Flat> = document
            .select(&flat_selector)
            .filter_map(|element| self.parse_flat(&element))
            .collect();

        info!("Found {} flats from {}", flats.len(), self.name());
        self.update_success();
        Ok(flats)
    }

    fn status(&self) -> WebsiteStatus {
        self.base.status.lock().unwrap().clone()
    }

    fn update_success(&self) {
        if let Ok(mut status) = self.base.status.lock() {
            status.update_success();
        }
    }

    fn update_error(&self, error: &str) {
        if let Ok(mut status) = self.base.status.lock() {
            status.update_error(error);
        }
    }

    fn should_backoff(&self) -> bool {
        if let (Ok(last_error), Ok(backoff)) = (
            self.base.last_error.lock(),
            self.base.backoff_duration.lock(),
        ) {
            if let Some(last_error_time) = *last_error {
                return last_error_time.elapsed() < *backoff;
            }
        }
        false
    }
}

/// Create all scrapers
pub fn create_scrapers(config: Config) -> Vec<Box<dyn Scraper>> {
    vec![
        Box::new(InBerlinWohnenScraper::new(config.clone())),
        Box::new(DegewoScraper::new(config.clone())),
        // Add more scrapers here as needed
    ]
}

/// Create HTTP client with optimized settings
pub fn create_client(config: &Config) -> BotResult<Client> {
    let client = Client::builder()
        .timeout(config.request_timeout_duration())
        .user_agent("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.4 Safari/605.1.15")
        .gzip(true)
        .build()?;

    Ok(client)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_scraper_creation() {
        let config = Config::default();
        let scrapers = create_scrapers(config.clone());

        assert!(!scrapers.is_empty());
        assert_eq!(scrapers[0].name(), "InBerlinWohnen");
        assert_eq!(scrapers[1].name(), "Degewo");
    }

    #[test]
    fn test_client_creation() {
        let config = Config::default();
        let client = create_client(&config);

        assert!(client.is_ok());
    }
}
