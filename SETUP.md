# Setup Guide

## Automated Setup (Recommended)

The easiest way to set up the bot is using the automated setup script:

```bash
./setup.sh
```

This will:
- ✅ Check Python installation
- ✅ Create virtual environment
- ✅ Install all dependencies
- ✅ Help you create config.json
- ✅ Test the installation
- ✅ Optionally set up systemd service (Raspberry Pi)

**That's it!** The setup script handles everything for you.

---

## Manual Setup

If you prefer to set things up manually, follow these steps:

### Quick Start (Development)

### 1. Install Dependencies

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure the Bot

Create or edit `config.json`:

```json
{
  "BOT_TOKEN": "your-telegram-bot-token",
  "CHAT_ID": "your-chat-id",
  "PRIVATE_CHAT_ID": "your-private-chat-id",
  "MONITOR_INTERVAL": 60
}
```

### 3. Run the Bot

**Option A: Using the convenience script**
```bash
./run.sh
```

**Option B: Manually**
```bash
source venv/bin/activate
python3 bot.py
```

## Production Setup (Raspberry Pi)

### 1. Install System Dependencies

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
```

### 2. Install Python Dependencies

```bash
# Create virtual environment
python3 -m venv venv

# Install dependencies
venv/bin/pip install -r requirements.txt
```

### 3. Configure SystemD Service

Edit `telegram.service` to use the virtual environment:

```ini
[Unit]
Description=Berlin Flat Monitor Bot
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/BerlinFlatBot
# Use virtual environment Python
ExecStart=/home/pi/BerlinFlatBot/venv/bin/python3 /home/pi/BerlinFlatBot/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 4. Install and Start Service

```bash
# Copy service file
sudo cp telegram.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable telegram.service

# Start service
sudo systemctl start telegram.service

# Check status
sudo systemctl status telegram.service

# View logs
journalctl -u telegram.service -f
```

### 5. Apply SD Card Optimizations (Recommended)

See `SD_CARD_OPTIMIZATION.md` for details on:
- Configuring journald for RAM storage
- Disabling swap
- Additional optimizations

## Troubleshooting

### "ModuleNotFoundError: No module named 'aiohttp'"

**Solution:** Activate the virtual environment first:
```bash
source venv/bin/activate
python3 bot.py
```

### "config.json not found"

**Solution:** Create the config file with your Telegram bot credentials:
```bash
cp config.json.example config.json  # if example exists
# OR
nano config.json  # and add your credentials
```

### Bot doesn't send notifications

**Possible causes:**
1. Check Telegram bot token is correct
2. Verify chat IDs are correct
3. Check bot has permission to send messages to the chat
4. View logs: `journalctl -u telegram.service -f`

### Cache not persisting after reboot

This is expected! Cache is now stored in RAM (`/dev/shm`) to protect your SD card. The bot will re-learn seen apartments after restart.

## Development Tips

### Running Tests

```bash
source venv/bin/activate
python3 -m pytest  # if tests exist
```

### Checking Logs (SystemD Service)

```bash
# Follow logs in real-time
journalctl -u telegram.service -f

# View last 50 lines
journalctl -u telegram.service -n 50

# View logs from today
journalctl -u telegram.service --since today
```

### Manual Testing

Test individual scrapers:

```bash
source venv/bin/activate
python3 -c "
import asyncio
from scrapers import InBerlinWohnenScraper

async def test():
    scraper = InBerlinWohnenScraper('https://inberlinwohnen.de/wohnungsfinder/')
    flats = await scraper.fetch_flats()
    print(f'Found {len(flats)} flats')
    for flat in flats[:3]:
        print(f'- {flat.title}')

asyncio.run(test())
"
```

### Clearing Cache

```bash
# Development (with virtual environment)
source venv/bin/activate
python3 -c "from scrapers import reset_seen_flats; reset_seen_flats()"

# Production (via Telegram)
# Send /clear command to the bot
```

## Project Structure

```
BerlinFlatBot/
├── bot.py                   # Main application
├── config.json              # Configuration (not in git)
├── requirements.txt         # Python dependencies
├── venv/                    # Virtual environment (not in git)
├── scrapers/                # Scrapers package
│   ├── __init__.py
│   ├── base.py              # Base classes
│   ├── cache.py             # Cache management
│   ├── session.py           # HTTP session
│   ├── inberlin.py          # InBerlinWohnen scraper
│   ├── degewo.py            # Degewo scraper
│   ├── gesobau.py           # Gesobau scraper
│   ├── gewobag.py           # Gewobag scraper
│   └── stadtundland.py      # Stadt und Land scraper
├── run.sh                   # Convenience run script
├── telegram.service         # SystemD service file
├── SETUP.md                 # This file
├── SD_CARD_OPTIMIZATION.md  # SD card protection guide
└── REFACTORING.md           # Code refactoring notes
```

## Next Steps

1. ✅ Install dependencies
2. ✅ Configure `config.json`
3. ✅ Test locally with `./run.sh`
4. Deploy to Raspberry Pi
5. Set up SystemD service
6. Apply SD card optimizations
7. Monitor logs to ensure everything works

## Getting Help

- Check logs: `journalctl -u telegram.service -f`
- Review `SD_CARD_OPTIMIZATION.md` for Raspberry Pi issues
- Review `REFACTORING.md` for code structure details
