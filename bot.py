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
    StadtUndLandScraper,  # Import the new scraper
    WebsiteUnavailableError,
    HighTrafficError,
    reset_seen_flats  # Add this import
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
        # Start with WBS icon
        icon = "🏠" if flat.wbs_required else "✅"
        
        # Create message with icon and title
        if flat.link:
            message = f"{icon} [*{flat.title}*]({flat.link})\n"
        else:
            message = f"{icon} *{flat.title}*\n"
            
        # Add details
        if flat.details:
            for key, value in flat.details.items():
                if value and value.strip():  # Only add non-empty values
                    message += f"• {key}: {value}\n"

        # Add scraper name as link
        if flat.link:
            message += f"[{flat.source}]({flat.link})\n"
        else:
            message += f"{flat.source}\n"
        return message

    @staticmethod
    def format_help_message() -> str:
        return (
            "🏠 *Berlin Flat Monitor*\n\n"
            "I monitor multiple housing websites for new flats and notify you when they appear.\n\n"
            "*Commands:*\n"
            "• /list [scraper] - Show latest flats (optionally filter by scraper)\n"
            "• /help - Show this help\n"
            "• /status - Show website status\n"
            "• /test - Test all scrapers\n"
            "• /clear - Clear the flat cache\n\n"
            "*Available scrapers:*\n"
            "• InBerlinWohnen\n"
            "• Degewo\n"
            "• Gesobau\n"
            "• Gewobag\n"
            "• Stadt und Land"
        )

    @staticmethod
    def format_status_message(website_statuses: Dict[str, str]) -> str:
        message = "🌐 *Website Status*\n\n"
        for website, status in website_statuses.items():
            status_lower = status.lower()
            if "not checked yet" in status_lower:
                message += f"*{website}*\n_⏳ {status}_\n\n"
            elif "unavailable" in status_lower or "error" in status_lower or "timeout" in status_lower:
                message += f"*{website}*\n_❌ {status}_\n\n"
            elif "high traffic" in status_lower:
                message += f"*{website}*\n_🚧 {status}_\n\n"
            else:
                message += f"*{website}*\n_✅ {status}_\n\n"
        return message

class FlatMonitor:
    def __init__(self, config: Config):
        self.config = config
        self.bot = Bot(token=config.bot_token)
        self.chat_id = config.chat_id
        self.private_chat_id = config.private_chat_id
        self.current_flats: List[FlatDetails] = []
        self.application: Optional[Application] = None
        self.formatter = MessageFormatter()
        
        # Initialize scrapers and their status
        self.scrapers = [
            InBerlinWohnenScraper("https://inberlinwohnen.de/wohnungsfinder/"),
            DegewoScraper("https://www.degewo.de/immosuche"),
            GesobauScraper("https://www.gesobau.de/mieten/wohnungssuche/"),
            GewobagScraper("https://www.gewobag.de/fuer-mieter-und-mietinteressenten/mietangebote/?objekttyp%5B%5D=wohnung&gesamtmiete_von=&gesamtmiete_bis=&gesamtflaeche_von=&gesamtflaeche_bis=&zimmer_von=&zimmer_bis=&sort-by="),
            StadtUndLandScraper("https://stadtundland.de/wohnungssuche")
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
        logger.info(f"Current flats in cache: {len(self.current_flats)}")
        
        # Get the scraper name from the command if provided
        scraper_name = None
        if context.args and len(context.args) > 0:
            scraper_name = context.args[0].strip()
            logger.info(f"Filtering by scraper: {scraper_name}")
        
        # Use cached flats
        flats = self.current_flats
        
        if not flats:
            logger.info("No flats in cache, fetching new ones...")
            flats = await self.fetch_all_flats()
            self.current_flats = flats  # Update cache with new flats
        
        if not flats:
            await update.message.reply_text("No flats available at the moment.")
            return

        try:
            # Filter flats by scraper if specified
            if scraper_name:
                flats = [flat for flat in flats if flat.source.lower() == scraper_name.lower()]
                if not flats:
                    await update.message.reply_text(f"No flats available from {scraper_name}.")
                    return

            total_flats = len(flats)
            logger.info(f"Total flats found: {total_flats}")
            flats = flats[:5]  # Limit to 5 flats
            
            # Add a header message
            header = f"Found {total_flats} flats"
            if scraper_name:
                header += f" from {scraper_name}"
            header += f" (showing {len(flats)}):"
            await update.message.reply_text(header)
            
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
            # Initial fetch
            self.current_flats = await self.fetch_all_flats()
            logger.info(f"Initialized with {len(self.current_flats)} existing flats")
        except Exception as e:
            error_msg = f"Failed to initialize flats: {str(e)}"
            logger.error(error_msg)
            await self.send_error_notification(error_msg)
            return

        while True:
            try:
                logger.info("Checking for new flats...")
                new_flats = await self.fetch_all_flats()
                
                # Find flats that weren't in the previous cache
                current_ids = {flat.id for flat in self.current_flats}
                new_entries = [flat for flat in new_flats if flat.id not in current_ids]
                if new_entries:
                    logger.info(f"Found {len(new_entries)} new flats")
                
                # Filter for flats with 2 or more rooms and not requiring WBS
                def get_room_count(flat):
                    # Try different possible room field names
                    room_fields = ['Zimmer', 'Zimmeranzahl', 'rooms']
                    for field in room_fields:
                        if field in flat.details:
                            try:
                                # Handle different formats: "2", "2 Zimmer", "2.0", etc.
                                room_str = flat.details[field].lower()
                                # Extract first number from string
                                import re
                                match = re.search(r'\d+(?:[.,]\d+)?', room_str)
                                if match:
                                    return float(match.group().replace(',', '.'))
                            except (ValueError, AttributeError):
                                continue
                    return 0  # Return 0 if no valid room count found
                
                two_or_more_rooms = [flat for flat in new_entries if (get_room_count(flat) == 0 or get_room_count(flat) >= 2) and not flat.wbs_required]
                if two_or_more_rooms:
                    logger.info(f"Found {len(two_or_more_rooms)} new flats with 2 or more rooms")
                    await self.send_update(two_or_more_rooms)
                
                # Update the cache
                self.current_flats = new_flats

            except Exception as e:
                error_msg = f"Error during monitoring: {str(e)}"
                logger.error(error_msg)
                await self.send_error_notification(error_msg)

            logger.info(f"Waiting {self.config.monitor_interval} seconds before next check...")
            await asyncio.sleep(self.config.monitor_interval)

    async def test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handles the /test command to return the first result of each scraper."""
        if str(update.effective_chat.id) != self.chat_id:
            return

        reset_seen_flats()  # Reset seen flats before starting
        message = "🏠 *Test Results*\n\n"
        
        for scraper in self.scrapers:
            try:
                flats = await scraper.fetch_flats()
                if flats:
                    flat = flats[0]  # Get the first flat
                    # Escape special characters in title and ensure proper Markdown formatting
                    safe_title = flat.title.replace('*', '\\*').replace('_', '\\_').replace('[', '\\[').replace(']', '\\]')
                    
                    # Create a minimal message with just the essential info
                    message += f"*{scraper.__class__.__name__}*\n"
                    if flat.link:
                        message += f"[_{safe_title}_]({flat.link})\n\n"
                    else:
                        message += f"_{safe_title}_\n\n"
                else:
                    message += f"*{scraper.__class__.__name__}*\n"
                    message += "_No flats found_\n\n"
            except Exception as e:
                message += f"*{scraper.__class__.__name__}*\n"
                message += f"_Error: {str(e)}_\n\n"

        try:
            await update.message.reply_text(
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        except TelegramError as e:
            logger.error(f"Failed to send test results: {e}")
            await self.send_error_notification(f"Failed to send test results: {e}")

    async def handle_clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if str(update.effective_chat.id) != self.chat_id:
            return

        try:
            self.current_flats = []
            await update.message.reply_text("✅ Flat cache cleared successfully!")
            logger.info("Flat cache cleared")
        except TelegramError as e:
            logger.error(f"Failed to send clear confirmation: {e}")
            await self.send_error_notification(f"Failed to send clear confirmation: {e}")

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
        application.add_handler(CommandHandler("test", monitor.test_command))
        application.add_handler(CommandHandler("clear", monitor.handle_clear_command))

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
