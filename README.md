# Berlin Flat Monitor Bot

A Telegram bot that monitors [inberlinwohnen.de](https://inberlinwohnen.de/wohnungsfinder/) for new flats and notifies you in real-time.

## Features

- 🔍 Monitors inberlinwohnen.de every minute for new flats
- 🏠 Notifies about new WBS flats
- ✅ Notifies about new non-WBS flats
- 📋 Shows all current flats on demand

## Commands

- `/list` - Show all current flats
- `/help` - Show help message

## Setup

1. Create a new Telegram bot using [@BotFather](https://t.me/botfather)
2. Get your bot token and chat ID
3. Create a `config.json` file with your credentials:
   ```json
   {
       "BOT_TOKEN": "your_bot_token_here",
       "CHAT_ID": "your_chat_id_here"
   }
   ```
4. Install the required Python packages:
   ```bash
   pip install python-telegram-bot beautifulsoup4 aiohttp
   ```
5. Run the bot:
   ```bash
   python3 bot.py
   ```

## Requirements

- Python 3.7+
- python-telegram-bot
- beautifulsoup4
- aiohttp

## Notes

- The bot must be added to a group chat to work
- Make sure to set the correct chat ID in the config file
- The bot will automatically notify about new flats every minute 