# Telegram Bot for Flat Monitoring

This bot monitors the inberlinwohnen.de website for new flat listings and sends updates to a Telegram group. It checks for new listings every minute and provides detailed information about each flat.

## Features

- Monitors inberlinwohnen.de every minute for new flats
- Extracts detailed information about each flat:
  - Address
  - Number of rooms
  - Living space
  - WBS status
  - Move-in date
  - Floor
  - Bathroom
  - Year built
- Separates flats into WBS and non-WBS categories
- Sends formatted messages with all details and links

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

To start monitoring for new flats, run:
```bash
python bot.py
```

## Example Output

The bot sends two types of messages:

### WBS Flats
```
🏠 New WBS Flats Available! (1)

*Flat Title*
• Adresse: Example Street 123
• Zimmeranzahl: 2
• Wohnfläche: 60 m²
• WBS: erforderlich
• Bezugsfertig ab: 01.01.2024
• Etage: 3
• Badezimmer: 1
• Baujahr: 2020

[View Details](link)
```

### Non-WBS Flats
```
✅ New Non-WBS Flats Available! (1)

*Flat Title*
• Adresse: Example Street 456
• Zimmeranzahl: 3
• Wohnfläche: 75 m²
• Bezugsfertig ab: 01.02.2024
• Etage: 4
• Badezimmer: 1
• Baujahr: 2021

[View Details](link)
```

## Notes

- The bot uses the flat's element ID (e.g., "flat_1271141") as a unique identifier
- Non-WBS flats are marked with a green checkmark (✅)
- WBS flats are marked with a house emoji (🏠)
- Each message includes a link to view more details about the flat
- The bot checks for new listings every minute
- Make sure your bot has permission to send messages in the group
- The bot must be a member of the group to send messages
- Keep your bot token secure and never share it publicly 