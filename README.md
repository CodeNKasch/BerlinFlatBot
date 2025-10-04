# Berlin Flat Monitor Bot 🏠

A Telegram bot that monitors Berlin housing websites for new apartment listings and sends real-time notifications. The bot runs continuously and checks for new listings at configurable intervals (default: every 60 seconds).

## Features

- **Active Monitoring**: Currently monitors InBerlinWohnen
- **Smart Filtering**: Only notifies about flats with 2+ rooms and no WBS requirement
- **Quiet Hours**: Notifications only sent between 8 AM - 8 PM (flats found outside these hours are buffered and sent at 8 AM)
- **Detailed Information**: Each notification includes:
  - Apartment title and direct link
  - Address and location details
  - Room count, living space, and pricing
  - WBS status indicator (✅ = no WBS required, 🏠 = WBS required)
- **Duplicate Prevention**: Global tracking prevents duplicate notifications
- **Error Resilience**: Automatic retry mechanism with exponential backoff
- **Website Status**: Monitor and track availability of scraping sources

## Prerequisites

- Python 3.7 or higher
- Telegram Bot Token (obtain from [@BotFather](https://t.me/botfather))
- Telegram Chat ID where notifications will be sent

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/BerlinFlatBot.git
cd BerlinFlatBot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `config.json` file with your settings:
```json
{
    "BOT_TOKEN": "your_telegram_bot_token",
    "CHAT_ID": "your_chat_id",
    "PRIVATE_CHAT_ID": "your_private_chat_id",
    "MONITOR_INTERVAL": 60
}
```

4. (Optional) Set up as a system service:
```bash
sudo cp telegram.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable telegram.service
sudo systemctl start telegram.service
```

## Usage

1. Start the bot:
```bash
python bot.py
```

2. Available Telegram commands:
- `/list [scraper]` - Show current available flats (filtered by 2+ rooms, no WBS)
  - Optional: specify scraper name to filter results (e.g., `/list InBerlinWohnen`)
- `/help` - Display help message with all available commands
- `/status` - Check website availability and scraper status
- `/test` - Test all configured scrapers and show first result from each
- `/clear` - Reset the flat cache (useful for re-seeing all current listings)

## System Requirements

- Python 3.7+
- Internet connection
- Sufficient disk space for caching (minimal)

## Dependencies

- python-telegram-bot>=20.7,<23.0
- aiohttp>=3.9.3,<4.0
- beautifulsoup4>=4.12.3,<5.0

## Troubleshooting

### `'Updater' object has no attribute '_Updater__polling_cleanup_cb'`

If you encounter this error, it's likely due to a version mismatch. Try:

```bash
pip install --upgrade python-telegram-bot
# or force reinstall
pip install --force-reinstall python-telegram-bot==20.7
```

Make sure you're using Python 3.7+ and have a clean virtual environment.

## Architecture

### Active Scrapers
Currently, only **InBerlinWohnen** is actively monitored. Other scrapers (Degewo, Gesobau, Gewobag, Stadt und Land) are implemented but commented out in `bot.py` (lines 159-162).

To enable additional scrapers, uncomment the desired lines in `bot.py`:
```python
self.scrapers = [
    InBerlinWohnenScraper("https://inberlinwohnen.de/wohnungsfinder/"),
    # DegewoScraper("https://www.degewo.de/immosuche"),
    # GesobauScraper("https://www.gesobau.de/mieten/wohnungssuche/"),
    # etc...
]
```

### Error Handling
- **Automatic Retry**: Failed requests retry with exponential backoff
- **High Traffic Detection**: Recognizes 503/429 status codes and backs off
- **Website Monitoring**: Tracks availability of each scraper
- **Private Notifications**: Errors reported to private chat ID for debugging

## How It Works

1. **Initialization**: Bot loads configuration and initializes active scrapers
2. **Monitoring Loop**: Runs every 60 seconds (configurable via `MONITOR_INTERVAL`)
3. **Fetching**: Each scraper fetches current apartment listings from its source
4. **Filtering**: New flats are checked against:
   - Room count (must be 2+ or unknown)
   - WBS requirement (must not be required)
   - Duplicate tracking (global ID cache)
5. **Notification**: Qualifying flats are sent to Telegram (respecting quiet hours)
6. **Buffering**: Flats found during quiet hours (8 PM - 8 AM) are buffered and sent at 8 AM

## Configuration

The `config.json` file requires:
- `BOT_TOKEN`: Your Telegram bot token from [@BotFather](https://t.me/botfather)
- `CHAT_ID`: Public chat ID where flat notifications are sent
- `PRIVATE_CHAT_ID`: Private chat ID for error notifications and debugging
- `MONITOR_INTERVAL`: Seconds between checks (default: 60)

## Disclaimer

This bot is for personal use only. Please respect the terms of service of the monitored websites and use responsibly. Web scraping may be against some websites' terms of service.
