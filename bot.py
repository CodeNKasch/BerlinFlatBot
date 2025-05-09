import asyncio
import logging
import json
from datetime import datetime
from typing import List, Set, Dict, Optional

import aiohttp
from bs4 import BeautifulSoup
from telegram import Bot, Update
from telegram.error import TelegramError, ChatMigrated
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from scrapers import (
    FlatDetails,
    InBerlinWohnenScraper,
    DegewoScraper,
    GesobauScraper,
    GewobagScraper,
    WebsiteUnavailableError,
    HighTrafficError
)

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

class Config:
    def __init__(self, config_path: str = 'config.json'):
        self.config_path = config_path
        self.bot_token: str = ""
        self.chat_id: str = ""
        self.private_chat_id: str = ""
        self.monitor_interval: int = 60
        self.load_config()

    def load_config(self):
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            
            self.bot_token = config['BOT_TOKEN']
            self.chat_id = config['CHAT_ID']
            self.private_chat_id = config['PRIVATE_CHAT_ID']
            self.monitor_interval = int(config.get('MONITOR_INTERVAL', 60))
            
            logger.info(f"Loaded configuration with monitor interval: {self.monitor_interval} seconds")
        except FileNotFoundError:
            raise RuntimeError("config.json not found!")
        except json.JSONDecodeError:
            raise RuntimeError("Invalid JSON in config.json!")
        except KeyError as e:
            raise RuntimeError(f"Missing required configuration: {e}")
        except Exception as e:
            raise RuntimeError(f"Error loading configuration: {e}")

class MessageFormatter:
    @staticmethod
    def format_flat_message(flat: FlatDetails) -> str:
        if flat.wbs_required:
            message = "🏠 (WBS) "
        else:
            message = "✅ (No WBS) "

        message += f"*{flat.title}* [{flat.source}]\n"

        # Add key details
        for key in [
            "Adresse",
            "Zimmeranzahl",
            "Wohnfläche",
            "WBS",
            "Bezugsfertig ab",
            "Etage",
            "Badezimmer",
            "Baujahr",
            "Miete",
            "Kaltmiete",
            "Warmmiete",
        ]:
            if key in flat.details:
                message += f"• {key}: {flat.details[key]}\n"

        # Add link
        if flat.link:
            message += f"\n[View Details]({flat.link})"

        return message

    @staticmethod
    def format_help_message() -> str:
        return (
            "🏠 *Berlin Flat Monitor Help*\n\n"
            "I monitor multiple housing websites for new flats and notify you when they appear.\n\n"
            "*Available Commands:*\n"
            "• /list - Show the latest 5 flats\n"
            "• /help - Show this help message\n"
            "• /status - Show the status of all monitored websites\n\n"
            "The bot will automatically notify you about:\n"
            "• New WBS flats 🏠\n"
            "• New non-WBS flats ✅\n"
            "• Website availability issues ⚠️\n\n"
            "Monitored websites:\n"
            "• InBerlinWohnen\n"
            "• Degewo\n"
            "• Gesobau\n"
            "• Gewobag"
        )

    @staticmethod
    def format_status_message(website_statuses: Dict[str, str]) -> str:
        message = "🌐 *Website Status*\n\n"
        for website, status in website_statuses.items():
            status_lower = status.lower()
            if "not checked yet" in status_lower:
                message += f"⏳ {website}: {status}\n"
            elif "unavailable" in status_lower or "error" in status_lower or "timeout" in status_lower:
                message += f"⚠️ {website}: {status}\n"
            elif "high traffic" in status_lower:
                message += f"🚧 {website}: {status}\n"
            else:
                message += f"✅ {website}: {status}\n"
        return message

class FlatMonitor:
    def __init__(self, config: Config):
        self.config = config
        self.bot = Bot(token=config.bot_token)
        self.chat_id = config.chat_id
        self.private_chat_id = config.private_chat_id
        self.last_flats: Set[str] = set()
        self.current_flats: List[FlatDetails] = []
        self.application: Optional[Application] = None
        self.formatter = MessageFormatter()
        
        # Initialize scrapers and their status
        self.scrapers = [
            InBerlinWohnenScraper("https://inberlinwohnen.de/wohnungsfinder/"),
            DegewoScraper("https://www.degewo.de/immosuche"),
            GesobauScraper("https://www.gesobau.de/mieten/wohnungssuche/"),
            GewobagScraper("https://www.gewobag.de/fuer-mieter-und-mietinteressenten/mietangebote/")
        ]
        # Initialize status for all scrapers
        self.website_statuses = {scraper.__class__.__name__: "Not checked yet" for scraper in self.scrapers}

    async def send_welcome(self):
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text="🏠 *Flat Monitor Started*\n\n"
                     "I will notify you about new flats every minute!\n\n"
                     "Available commands:\n"
                     "• /list - Show all current flats\n"
                     "• /help - Show this help message\n"
                     "• /status - Show website status",
                parse_mode="Markdown",
            )
            logger.info(f"Welcome message sent to chat {self.chat_id}")
        except TelegramError as e:
            error_msg = f"Failed to send welcome message: {str(e)}"
            logger.error(error_msg)
            await self.send_error_notification(error_msg)
            
            if isinstance(e, ChatMigrated):
                self.chat_id = str(e.new_chat_id)
                logger.info(f"Updated chat ID to {self.chat_id}")
                try:
                    await self.bot.send_message(
                        chat_id=self.chat_id,
                        text="🏠 *Flat Monitor Started*\n\n"
                             "I will notify you about new flats every minute!\n\n"
                             "Available commands:\n"
                             "• /list - Show all current flats\n"
                             "• /help - Show this help message\n"
                             "• /status - Show website status",
                        parse_mode="Markdown",
                    )
                    logger.info(f"Welcome message sent to new chat {self.chat_id}")
                    return
                except TelegramError as retry_error:
                    error_msg = f"Failed to send welcome message to new chat: {str(retry_error)}"
                    logger.error(error_msg)
                    await self.send_error_notification(error_msg)
            
            exit()

    async def handle_help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if str(update.effective_chat.id) != self.chat_id:
            return

        try:
            await update.message.reply_text(
                text=self.formatter.format_help_message(),
                parse_mode="Markdown",
            )
            logger.info("Help message sent")
        except TelegramError as e:
            logger.error(f"Failed to send help message: {e}")

    async def handle_status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if str(update.effective_chat.id) != self.chat_id:
            return

        try:
            # Update statuses before showing
            await self.fetch_all_flats()
            
            status_message = self.formatter.format_status_message(self.website_statuses)
            await update.message.reply_text(
                text=status_message,
                parse_mode="Markdown",
            )
            logger.info("Status message sent")
        except TelegramError as e:
            logger.error(f"Failed to send status message: {e}")
            await self.send_error_notification(f"Failed to send status message: {e}")

    async def fetch_all_flats(self) -> List[FlatDetails]:
        """Fetch flats from all sources."""
        all_flats = []
        for scraper in self.scrapers:
            try:
                flats = await scraper.fetch_flats()
                all_flats.extend(flats)
                self.website_statuses[scraper.__class__.__name__] = "Available"
            except WebsiteUnavailableError as e:
                logger.error(f"Website unavailable: {e}")
                self.website_statuses[scraper.__class__.__name__] = str(e)
            except HighTrafficError as e:
                logger.error(f"High traffic: {e}")
                self.website_statuses[scraper.__class__.__name__] = str(e)
            except asyncio.TimeoutError as e:
                logger.error(f"Timeout error: {e}")
                self.website_statuses[scraper.__class__.__name__] = "Timeout - Website not responding"
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                self.website_statuses[scraper.__class__.__name__] = f"Error: {str(e)}"
        return all_flats

    async def send_update(self, new_flats: List[FlatDetails]):
        if not new_flats:
            return

        try:
            for flat in new_flats:
                message = self.formatter.format_flat_message(flat)
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                )
        except TelegramError as e:
            logger.error(f"Failed to send update: {e}")

    async def handle_list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info(f"Received command: {update.message.text}")
        logger.info(f"Chat ID: {update.effective_chat.id}")
        logger.info(f"Expected Chat ID: {self.chat_id}")
        
        if str(update.effective_chat.id) != self.chat_id:
            logger.info("Message not from target chat, ignoring")
            return

        logger.info("Processing list command")
        
        flats = await self.fetch_all_flats()
        
        if not flats:
            await update.message.reply_text("No flats available at the moment.")
            return

        try:
            total_flats = len(flats)
            flats = flats[:5]  # Limit to 5 flats
            for flat in flats:
                message = self.formatter.format_flat_message(flat)
                await update.message.reply_text(
                    text=message,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                )
            logger.info(f"Sent {len(flats)} flats")
        except TelegramError as e:
            logger.error(f"Failed to send list: {e}")

    async def send_error_notification(self, error_message: str):
        try:
            await self.bot.send_message(
                chat_id=self.private_chat_id,
                text=f"⚠️ *Error in Flat Monitor*\n\n{error_message}",
                parse_mode="Markdown",
            )
            logger.info(f"Error notification sent to private chat {self.private_chat_id}")
        except TelegramError as e:
            logger.error(f"Failed to send error notification: {e}")

    async def monitor(self):
        logger.info("Starting monitoring loop...")
        await self.send_welcome()

        try:
            initial_flats = await self.fetch_all_flats()
            self.last_flats = {flat.id for flat in initial_flats}
            logger.info(f"Initialized with {len(self.last_flats)} existing flats")
        except Exception as e:
            error_msg = f"Failed to initialize flats: {str(e)}"
            logger.error(error_msg)
            await self.send_error_notification(error_msg)
            return

        while True:
            try:
                logger.info("Checking for new flats...")
                current_flats = await self.fetch_all_flats()
                current_flat_set = {flat.id for flat in current_flats}

                new_flats = [flat for flat in current_flats if flat.id not in self.last_flats]

                if new_flats:
                    logger.info(f"Found {len(new_flats)} new flats")
                    await self.send_update(new_flats)
                else:
                    logger.info("No new flats found")

                self.last_flats = current_flat_set

            except Exception as e:
                error_msg = f"Error during monitoring: {str(e)}"
                logger.error(error_msg)
                await self.send_error_notification(error_msg)

            logger.info(f"Waiting {self.config.monitor_interval} seconds before next check...")
            await asyncio.sleep(self.config.monitor_interval)

async def main():
    try:
        config = Config()
        monitor = FlatMonitor(config)

        application = (
            Application.builder()
            .token(config.bot_token)
            .concurrent_updates(True)
            .build()
        )
        monitor.application = application

        application.add_handler(CommandHandler("list", monitor.handle_list_command))
        application.add_handler(CommandHandler("help", monitor.handle_help_command))
        application.add_handler(CommandHandler("status", monitor.handle_status_command))

        monitoring_task = asyncio.create_task(monitor.monitor())
        
        await application.initialize()
        await application.start()
        
        try:
            logger.info("Starting polling...")
            await application.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True
            )
            logger.info("Polling started successfully")
            
            while True:
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Error during polling: {e}")
        finally:
            monitoring_task.cancel()
            try:
                await monitoring_task
            except asyncio.CancelledError:
                pass
            await application.stop()

    except Exception as e:
        logger.error(f"Bot stopped due to error: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot stopped due to error: {e}")
