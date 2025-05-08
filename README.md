# Telegram Bot for Group Messages

This is a simple Python script that allows you to send messages to Telegram chat groups using a bot.

## Setup Instructions

1. First, create a new bot and get your bot token:
   - Open Telegram and search for "@BotFather"
   - Start a chat with BotFather
   - Send the command `/newbot`
   - Follow the instructions to create your bot
   - BotFather will give you a token - save this token

2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Get your chat ID:
   - Add your bot to the group where you want to send messages
   - Send a message in the group
   - Visit this URL in your browser (replace YOUR_BOT_TOKEN with your actual token):
     ```
     https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates
     ```
   - Look for the "chat" object in the response, which will contain the "id" field
   - The chat ID will be a negative number for groups

4. Update the `bot.py` file:
   - Replace `YOUR_BOT_TOKEN` with your actual bot token
   - Replace `YOUR_CHAT_ID` with your actual chat ID

## Usage

To send a message to your group, run:
```bash
python bot.py
```

You can also import the `TelegramBot` class in your own scripts:

```python
from bot import TelegramBot
import asyncio

async def main():
    bot = TelegramBot("YOUR_BOT_TOKEN")
    await bot.send_message("YOUR_CHAT_ID", "Your message here")

asyncio.run(main())
```

## Notes

- Make sure your bot has permission to send messages in the group
- The bot must be a member of the group to send messages
- Keep your bot token secure and never share it publicly 