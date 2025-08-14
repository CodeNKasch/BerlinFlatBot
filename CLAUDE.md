# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

BerlinFlatBot is a Python-based Telegram bot that monitors Berlin housing websites for new apartment listings. The bot scrapes multiple housing websites and sends real-time notifications via Telegram when new apartments become available.

## Development Commands

### Setup and Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot directly
python3 bot.py

# Set up as system service (Linux)
sudo cp telegram.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable telegram.service
sudo systemctl start telegram.service
```

### Configuration

- Create `config.json` with Telegram bot token and chat IDs
- Monitor interval is configurable (default: 60 seconds)
- The bot requires BOT_TOKEN, CHAT_ID, PRIVATE_CHAT_ID, and MONITOR_INTERVAL

## Architecture

### Core Components

**bot.py** - Main application entry point containing:

- `FlatBot` class - Main bot orchestrator with Telegram handlers
- `Config` class - Configuration management from config.json
- Telegram command handlers: `/help`, `/status`, `/list`, `/test`, `/clear`
- Background monitoring loop that checks all scrapers periodically

**scrapers.py** - Web scraping infrastructure with:

- `BaseScraper` - Abstract base class for all housing website scrapers
- Individual scrapers for each housing website:
  - `InBerlinWohnenScraper` - InBerlinWohnen website
  - `DegewoScraper` - Degewo housing website
  - `GesobauScraper` - Gesobau housing website
  - `GewobagScraper` - Gewobag housing website
  - `StadtUndLandScraper` - Stadt und Land website
- `FlatDetails` dataclass - Standardized apartment data structure
- Global session management with connection pooling
- Error handling with `WebsiteUnavailableError` and `HighTrafficError`

### Key Design Patterns

- **Scraper Pattern**: Each housing website has its own scraper class inheriting from `BaseScraper`
- **Global Session Management**: Single aiohttp session shared across all scrapers for connection pooling
- **Duplicate Detection**: Global `_seen_flat_ids` set prevents duplicate notifications
- **Error Resilience**: Scrapers continue working even if individual websites fail
- **Rate Limiting**: Built-in backoff strategies for high traffic situations

### Data Flow

1. Background monitoring loop runs every N seconds (configurable)
2. Each scraper fetches and parses its target website
3. New apartments are filtered against seen IDs cache
4. Notifications sent to both public and private Telegram chats
5. Website status and errors reported to private chat

### Telegram Bot Commands

- `/list [scraper]` - Show current available apartments (optionally filtered by scraper)
- `/status` - Display website availability status
- `/test` - Test all scrapers and show results
- `/help` - Show available commands
- `/clear` - Reset the seen flats cache

## Dependencies

- `python-telegram-bot==20.7` - Telegram Bot API wrapper
- `aiohttp==3.9.3` - Async HTTP client for web scraping
- `beautifulsoup4==4.12.3` - HTML parsing and scraping

## Configuration Notes

The bot caches seen apartment IDs in `flats_cache.json` to prevent duplicate notifications. This file persists between bot restarts to maintain state.

All scrapers are designed to be resilient - if one website fails, others continue working. Error states are reported to the private chat for monitoring.

