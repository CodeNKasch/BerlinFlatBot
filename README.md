# Berlin Flat Bot

A Telegram bot that monitors inberlinwohnen.de for new flats and notifies you when they appear.

## Features

- Monitors inberlinwohnen.de for new flats
- Sends notifications for new WBS and non-WBS flats
- Lists current flats with the `/list` command
- Shows help information with the `/help` command

## Configuration

The bot uses a `config.json` file for configuration. Create this file in the root directory with the following structure:

```json
{
  "BOT_TOKEN": "YOUR_BOT_TOKEN",
  "CHAT_ID": "YOUR_CHAT_ID",
  "MONITOR_INTERVAL": 60
}
```

### Configuration Options

- `BOT_TOKEN`: Your Telegram bot token (obtained from @BotFather)
- `CHAT_ID`: The ID of the chat where the bot should send notifications
- `MONITOR_INTERVAL`: The interval in seconds between checks for new flats (default: 60)

## Installation

1. Clone this repository
2. Install the required packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Create and configure your `config.json` file
4. Run the bot:
   ```bash
   python bot.py
   ```

## Usage

- The bot will automatically start monitoring for new flats
- Use `/list` to see current flats (limited to 5 per category)
- Use `/help` to see available commands

## Service

To Run it as a debian service at startup you can use

```bash
cat > /etc/systemd/system/telegram-bot.service <<EOF
[Unit]
Description=Runs the python backend for a telegram bot.
After=network.target

[Service]
WorkingDirectory=/home/user/Projects/BerlinFlatBot
# use your project path and user!
ExecStart=/usr/bin/python3 /home/user/Projects/BerlinFlatBot/bot.py
User=user
Group=user
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable telegram-bot
sudo reboot
```

## Requirements

- Python 3.7+
- Required packages listed in requirements.txt
