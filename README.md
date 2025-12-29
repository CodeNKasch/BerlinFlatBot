# Berlin Flat Monitor Bot 🏠

A Telegram bot that monitors Berlin housing websites for new apartment listings and sends real-time notifications. The bot runs continuously and checks for new listings at configurable intervals (default: every 60 seconds).

> **Note:** Public version available at [Codeberg](https://codeberg.org/CodeNKasch/BerlinFlatBot)

## Features

- 🔍 **Multi-site monitoring** - Scrapes multiple Berlin housing websites
- 📱 **Telegram notifications** - Instant alerts for new apartments
- 🎯 **Smart filtering** - Filter by rooms, WBS requirement
- 💾 **Duplicate detection** - Never get notified twice
- 🔄 **Resilient** - Continues working even if one website fails
- 💿 **SD card optimized** - Minimal writes for Raspberry Pi deployment

## Quick Start

### One-Command Setup

```bash
./setup.sh
```

The setup script will automatically:
- ✅ Check Python installation
- ✅ Create virtual environment
- ✅ Install dependencies
- ✅ Help create config.json
- ✅ Test installation
- ✅ Optionally set up systemd service (Raspberry Pi)

### Running the Bot

```bash
# Development
./run.sh

# Production (Raspberry Pi with systemd)
sudo systemctl start telegram.service
```

## Supported Websites

- InBerlinWohnen
- Degewo
- Gesobau
- Gewobag
- Stadt und Land

## Bot Commands

- `/list` - Show current available apartments
- `/status` - Check website status
- `/test` - Test all scrapers
- `/clear` - Reset cache
- `/help` - Show commands

## Documentation

- **[SETUP.md](SETUP.md)** - Complete setup guide
- **[SD_CARD_OPTIMIZATION.md](SD_CARD_OPTIMIZATION.md)** - Raspberry Pi optimizations
- **[REFACTORING.md](REFACTORING.md)** - Code architecture

## Requirements

- Python 3.9+
- Telegram bot token
- Internet connection

## Project Structure

```
scrapers/          # Modular scraper package
├── base.py       # Base classes
├── cache.py      # RAM-based caching
├── session.py    # HTTP session
├── inberlin.py   # InBerlinWohnen scraper
├── degewo.py     # Degewo scraper
├── gesobau.py    # Gesobau scraper
├── gewobag.py    # Gewobag scraper
└── stadtundland.py # Stadt und Land scraper
```

## License

See [LICENSE](LICENSE) file.

---

**Happy apartment hunting!** 🎯
