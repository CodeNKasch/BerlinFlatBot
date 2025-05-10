# Berlin Flat Monitor Bot 🏠

A Telegram bot that monitors multiple Berlin housing websites for new apartment listings and notifies you in real-time. The bot checks for new listings every minute and sends notifications when new apartments become available.

## Features

- Monitors multiple Berlin housing websites:
  - InBerlinWohnen
  - Degewo
  - Gesobau
  - Gewobag
  - Stadt und Land
- Real-time notifications via Telegram
- Detailed apartment information including:
  - Title and link
  - WBS status
  - Price, size, and room details
  - Location information
- Website status monitoring
- Duplicate detection to avoid spam
- Error handling and automatic retry mechanism
- High traffic detection and backoff strategy

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

2. Available commands in Telegram:
- `/list` - Show all current flats
- `/help` - Show help message
- `/status` - Show website status
- `/test` - Test all scrapers

## System Requirements

- Python 3.7+
- Internet connection
- Sufficient disk space for caching (minimal)

## Dependencies

- python-telegram-bot==20.7
- aiohttp==3.9.3
- beautifulsoup4==4.12.3

## Error Handling

The bot includes robust error handling:
- Automatic retry mechanism for failed requests
- Backoff strategy for high traffic situations
- Website status monitoring
- Error notifications to private chat

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This bot is for personal use only. Please respect the terms of service of the monitored websites and use responsibly.
