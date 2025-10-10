import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Set

import aiohttp
from bs4 import BeautifulSoup
from telegram import Bot, Update
from telegram.error import ChatMigrated, TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from scrapers import StadtUndLandScraper  # Import the new scraper
from scrapers import reset_seen_flats, load_seen_flats, save_seen_flats  # Add these imports
from scrapers import (
    DegewoScraper,
    FlatDetails,
    GesobauScraper,
    GewobagScraper,
    HighTrafficError,
    InBerlinWohnenScraper,
    WebsiteUnavailableError,
)

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


class Config:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.bot_token: str = ""
        self.chat_id: str = ""
        self.private_chat_id: str = ""
        self.monitor_interval: int = 60
        self.load_config()

    def load_config(self):
        try:
            with open(self.config_path, "r") as f:
                config = json.load(f)

            self.bot_token = config["BOT_TOKEN"]
            self.chat_id = config["CHAT_ID"]
            self.private_chat_id = config["PRIVATE_CHAT_ID"]
            self.monitor_interval = int(config.get("MONITOR_INTERVAL", 60))

            logger.info(
                f"Loaded configuration with monitor interval: {self.monitor_interval} seconds"
            )
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
                if value:  # Check if value exists
                    # Convert non-string values to strings and handle them properly
                    if isinstance(value, str):
                        if value.strip():  # Only add non-empty strings
                            message += f"• {key}: {value}\n"
                    elif isinstance(value, (list, dict)):
                        # Skip complex data structures that don't display well
                        continue
                    else:
                        # Convert other types to strings
                        str_value = str(value).strip()
                        if str_value:
                            message += f"• {key}: {str_value}\n"

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
            elif (
                "unavailable" in status_lower
                or "error" in status_lower
                or "timeout" in status_lower
            ):
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
        self.buffered_flats: List[FlatDetails] = []  # Buffer for flats outside allowed hours
        self.application: Optional[Application] = None
        self.formatter = MessageFormatter()

        # Initialize scrapers and their status
        self.scrapers = [
            InBerlinWohnenScraper("https://inberlinwohnen.de/wohnungsfinder/"),
            # DegewoScraper("https://www.degewo.de/immosuche"),
            # GesobauScraper("https://www.gesobau.de/mieten/wohnungssuche/"),
            # GewobagScraper("https://www.gewobag.de/fuer-mieter-und-mietinteressenten/mietangebote/?objekttyp%5B%5D=wohnung&gesamtmiete_von=&gesamtmiete_bis=&gesamtflaeche_von=&gesamtflaeche_bis=&zimmer_von=&zimmer_bis=&sort-by="),
            # StadtUndLandScraper("https://stadtundland.de/wohnungssuche")
        ]
        # Initialize status for all scrapers
        self.website_statuses = {
            scraper.__class__.__name__: "Not checked yet" for scraper in self.scrapers
        }

    async def send_welcome(self):
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text="🏠 *Berlin Flat Monitor Started*\n\n"
                "I'm now actively monitoring Berlin housing websites for new apartments that match your criteria:\n"
                "✅ 2+ rooms\n"
                "✅ No WBS required\n\n"
                f"📊 *Monitoring {len(self.scrapers)} housing website(s)*\n"
                f"🔄 *Check interval: {self.config.monitor_interval} seconds*\n"
                "🕐 *Notifications: 8 AM - 8 PM*\n\n"
                "*Quick Commands:*\n"
                "• /list - Show current available flats\n"
                "• /status - Check website availability\n"
                "• /help - View all commands\n\n"
                "_You'll be notified instantly when matching apartments appear!_",
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
                        text="🏠 *Berlin Flat Monitor Started*\n\n"
                        "I'm now actively monitoring Berlin housing websites for new apartments that match your criteria:\n"
                        "✅ 2+ rooms\n"
                        "✅ No WBS required\n\n"
                        f"📊 *Monitoring {len(self.scrapers)} housing website(s)*\n"
                        f"🔄 *Check interval: {self.config.monitor_interval} seconds*\n"
                        "🕐 *Notifications: 8 AM - 8 PM*\n\n"
                        "*Quick Commands:*\n"
                        "• /list - Show current available flats\n"
                        "• /status - Check website availability\n"
                        "• /help - View all commands\n\n"
                        "_You'll be notified instantly when matching apartments appear!_",
                        parse_mode="Markdown",
                    )
                    logger.info(f"Welcome message sent to new chat {self.chat_id}")
                    return
                except TelegramError as retry_error:
                    error_msg = f"Failed to send welcome message to new chat: {str(retry_error)}"
                    logger.error(error_msg)
                    await self.send_error_notification(error_msg)

            exit()

    async def handle_help_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
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

    async def handle_status_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
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
                self.website_statuses[scraper.__class__.__name__] = (
                    "Timeout - Website not responding"
                )
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                self.website_statuses[scraper.__class__.__name__] = f"Error: {str(e)}"
        return all_flats

    async def send_update(self, new_flats: List[FlatDetails]):
        if not new_flats:
            return

        # Check if current time is within allowed hours (8 AM - 8 PM)
        current_hour = datetime.now().hour
        if not (8 <= current_hour < 20):
            logger.info(f"Outside allowed hours ({current_hour}:00) - buffering {len(new_flats)} flats for later")
            self.buffered_flats.extend(new_flats)
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

    async def send_buffered_flats(self):
        """Send any buffered flats if we're in allowed hours"""
        if not self.buffered_flats:
            return

        current_hour = datetime.now().hour
        if 8 <= current_hour < 20:
            logger.info(f"Sending {len(self.buffered_flats)} buffered flats")
            # Store buffer locally and clear immediately to prevent re-sending on failure
            flats_to_send = self.buffered_flats.copy()
            self.buffered_flats.clear()

            try:
                sent_count = 0
                for flat in flats_to_send:
                    message = self.formatter.format_flat_message(flat)
                    await self.bot.send_message(
                        chat_id=self.chat_id,
                        text=message,
                        parse_mode="Markdown",
                        disable_web_page_preview=True,
                    )
                    sent_count += 1
                logger.info(f"Successfully sent {sent_count} buffered flats")
            except TelegramError as e:
                logger.error(f"Failed to send buffered flats after sending {sent_count}/{len(flats_to_send)}: {e}")

    async def handle_list_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
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
                flats = [
                    flat
                    for flat in flats
                    if flat.source.lower() == scraper_name.lower()
                ]
                if not flats:
                    await update.message.reply_text(
                        f"No flats available from {scraper_name}."
                    )
                    return

            # Apply WBS and room filters (same as monitoring loop)
            def get_room_count(flat):
                room_fields = ["Zimmer", "Zimmeranzahl", "rooms"]
                for field in room_fields:
                    if field in flat.details:
                        try:
                            room_str = flat.details[field].lower()
                            import re
                            match = re.search(r"\d+(?:[.,]\d+)?", room_str)
                            if match:
                                return float(match.group().replace(",", "."))
                        except (ValueError, AttributeError):
                            continue
                return 0

            # Filter for 2+ rooms and no WBS requirement
            filtered_flats = [
                flat
                for flat in flats
                if (get_room_count(flat) == 0 or get_room_count(flat) >= 2)
                and not flat.wbs_required
            ]

            total_flats = len(flats)
            filtered_count = len(filtered_flats)
            logger.info(f"Total flats found: {total_flats}, after filters: {filtered_count}")
            flats = filtered_flats[:5]  # Limit to 5 flats

            # Add a header message
            if not flats:
                header = f"Found {total_flats} flats total, but none match filters (2+ rooms, no WBS)"
                if scraper_name:
                    header = f"Found {total_flats} flats from {scraper_name}, but none match filters (2+ rooms, no WBS)"
                await update.message.reply_text(header)
                return

            header = f"Found {total_flats} flats ({filtered_count} after filters, showing {len(flats)})"
            if scraper_name:
                header = f"Found {total_flats} flats from {scraper_name} ({filtered_count} after filters, showing {len(flats)})"
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
            logger.info(
                f"Error notification sent to private chat {self.private_chat_id}"
            )
        except TelegramError as e:
            logger.error(f"Failed to send error notification: {e}")

    async def monitor(self):
        logger.info("Starting monitoring loop...")

        # Load seen flats cache to prevent duplicates across restarts
        load_seen_flats()

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
                # Check and send any buffered flats if we're in allowed hours
                await self.send_buffered_flats()

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
                    room_fields = ["Zimmer", "Zimmeranzahl", "rooms"]
                    for field in room_fields:
                        if field in flat.details:
                            try:
                                # Handle different formats: "2", "2 Zimmer", "2.0", etc.
                                room_str = flat.details[field].lower()
                                # Extract first number from string
                                import re

                                match = re.search(r"\d+(?:[.,]\d+)?", room_str)
                                if match:
                                    return float(match.group().replace(",", "."))
                            except (ValueError, AttributeError):
                                continue
                    return 0  # Return 0 if no valid room count found

                # Debug output for all new entries
                if new_entries:
                    logger.info(
                        f"\n{'='*80}\n🔍 DEBUG: Found {len(new_entries)} new flats, checking filters...\n{'='*80}"
                    )
                    for flat in new_entries:
                        room_count = get_room_count(flat)
                        passes_room_filter = room_count == 0 or room_count >= 2
                        passes_wbs_filter = not flat.wbs_required
                        passes_all = passes_room_filter and passes_wbs_filter

                        status_icon = "✅ PASS" if passes_all else "❌ FILTERED"
                        logger.info(f"\n{status_icon} - {flat.source}")
                        logger.info(f"  Title: {flat.title}")
                        logger.info(f"  Link: {flat.link}")
                        logger.info(
                            f"  Rooms: {room_count} → {'✓' if passes_room_filter else '✗ (need 2+)'}"
                        )
                        logger.info(
                            f"  WBS: {'❌ Required' if flat.wbs_required else '✅ Not required'} → {'✓' if passes_wbs_filter else '✗ (filtered)'}"
                        )
                        if flat.details:
                            logger.info(f"  Details: {flat.details}")
                        logger.info(
                            f"  → Final: {'WILL NOTIFY USER' if passes_all else 'FILTERED OUT'}"
                        )
                    logger.info(f"\n{'='*80}\n")

                two_or_more_rooms = [
                    flat
                    for flat in new_entries
                    if (get_room_count(flat) == 0 or get_room_count(flat) >= 2)
                    and not flat.wbs_required
                ]
                if two_or_more_rooms:
                    logger.info(f"✉️  Sending {len(two_or_more_rooms)} flats to user")
                    await self.send_update(two_or_more_rooms)
                    # Save cache only when new flats are found to minimize SD card writes
                    save_seen_flats()
                else:
                    logger.info(f"ℹ️  No flats passed filters (all were filtered out)")

                # Update the cache
                self.current_flats = new_flats

            except Exception as e:
                error_msg = f"Error during monitoring: {str(e)}"
                logger.error(error_msg)
                await self.send_error_notification(error_msg)

            logger.info(
                f"Waiting {self.config.monitor_interval} seconds before next check..."
            )
            await asyncio.sleep(self.config.monitor_interval)

    async def test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handles the /test command to return the first result of each scraper."""
        if str(update.effective_chat.id) != self.chat_id:
            return

        reset_seen_flats()
        message = "🏠 *Test Results*\n\n"

        for scraper in self.scrapers:
            try:
                flats = await scraper.fetch_flats()
                if flats:
                    flat = flats[0]
                    message += f"*{scraper.__class__.__name__}*\n"
                    message += self.formatter.format_flat_message(flat)
                    message += "\n"
                else:
                    message += f"*{scraper.__class__.__name__}*\n_No flats found_\n\n"
            except Exception as e:
                message += f"*{scraper.__class__.__name__}*\n_Error: {str(e)}_\n\n"
                logger.error(f"Test failed for {scraper.__class__.__name__}: {e}")

        try:
            await update.message.reply_text(
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        except TelegramError as e:
            logger.error(f"Failed to send test results: {e}")
            await self.send_error_notification(f"Failed to send test results: {e}")

    async def handle_clear_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if str(update.effective_chat.id) != self.chat_id:
            return

        try:
            self.current_flats = []
            self.buffered_flats = []
            reset_seen_flats()
            await update.message.reply_text("✅ All caches cleared successfully (current flats, buffered flats, and seen flats)!")
            logger.info("All caches cleared (current, buffered, and seen flats)")
        except TelegramError as e:
            logger.error(f"Failed to send clear confirmation: {e}")
            await self.send_error_notification(
                f"Failed to send clear confirmation: {e}"
            )


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
                allowed_updates=Update.ALL_TYPES, drop_pending_updates=True
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
            # Save cache on shutdown
            logger.info("Shutting down, saving cache...")
            save_seen_flats(force=True)
            await application.stop()

    except Exception as e:
        logger.error(f"Bot stopped due to error: {e}")
        # Save cache even on error
        save_seen_flats(force=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot stopped due to error: {e}")
