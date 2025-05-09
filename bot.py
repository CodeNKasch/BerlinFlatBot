import asyncio
import logging
import json
from datetime import datetime
from dataclasses import dataclass
from typing import List, Set, Dict, Optional

import aiohttp
from bs4 import BeautifulSoup
from telegram import Bot, Update
from telegram.error import TelegramError, ChatMigrated
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

@dataclass
class FlatDetails:
    id: str
    title: str
    link: Optional[str]
    details: Dict[str, str]
    wbs_required: bool

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

        message += f"*{flat.title}*\n"

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
            "I monitor inberlinwohnen.de for new flats and notify you when they appear.\n\n"
            "*Available Commands:*\n"
            "• /list - Show the latest 5 flats\n"
            "• /help - Show this help message\n\n"
            "The bot will automatically notify you about:\n"
            "• New WBS flats 🏠\n"
            "• New non-WBS flats ✅"
        )

class FlatScraper:
    def __init__(self, url: str):
        self.url = url

    async def fetch_flats(self) -> List[FlatDetails]:
        logger.info("Fetching flats from website...")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.url) as response:
                    if response.status == 200:
                        html = await response.text()
                        logger.info(f"Received HTML response of length: {len(html)}")
                        
                        soup = BeautifulSoup(html, "html.parser")
                        flats = []

                        flat_elements = soup.find_all("li", id=lambda x: x and x.startswith("flat_"))
                        logger.info(f"Found {len(flat_elements)} flat elements in HTML")

                        for flat in flat_elements:
                            flat_details = self._extract_flat_details(flat)
                            if flat_details:
                                flats.append(flat_details)
                            else:
                                logger.warning(f"Failed to extract details for flat element: {flat.get('id', 'unknown')}")

                        logger.info(f"Successfully parsed {len(flats)} flats")
                        return flats
                    else:
                        logger.error(f"Failed to fetch flats. Status code: {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Error fetching flats: {e}")
            return []

    def _extract_flat_details(self, flat_element) -> Optional[FlatDetails]:
        try:
            flat_id = flat_element.get("id", "")
            logger.debug(f"Processing flat with ID: {flat_id}")

            title = flat_element.find("h2")
            title_text = title.text.strip() if title else "No title"
            logger.debug(f"Found title: {title_text}")

            link = None
            link_element = flat_element.find("a", class_="org-but")
            if link_element:
                link = link_element["href"]
                if not link.startswith("http"):
                    link = f"https://inberlinwohnen.de{link}"
                logger.debug(f"Found link: {link}")

            details = {}
            tables = flat_element.find_all("table", class_="tb-small-data")
            for table in tables:
                for row in table.find_all("tr"):
                    th = row.find("th")
                    td = row.find("td")
                    if th and td:
                        key = th.text.strip().rstrip(":")
                        value = td.text.strip()
                        details[key] = value
                        logger.debug(f"Found detail - {key}: {value}")

            features = []
            feature_spans = flat_element.find_all("span", class_="hackerl")
            for span in feature_spans:
                features.append(span.text.strip())
            if features:
                details["Features"] = ", ".join(features)

            wbs_required = False
            wbs_text = details.get("WBS", "").lower()
            if "erforderlich" in wbs_text or "wbs" in wbs_text:
                wbs_required = True
            logger.debug(f"WBS required: {wbs_required}")

            return FlatDetails(
                id=flat_id,
                title=title_text,
                link=link,
                details=details,
                wbs_required=wbs_required
            )
        except Exception as e:
            logger.error(f"Error extracting flat details: {e}")
            return None

class FlatMonitor:
    def __init__(self, config: Config):
        self.config = config
        self.bot = Bot(token=config.bot_token)
        self.chat_id = config.chat_id
        self.private_chat_id = config.private_chat_id
        self.last_flats: Set[str] = set()
        self.current_flats: List[FlatDetails] = []
        self.application: Optional[Application] = None
        self.scraper = FlatScraper("https://inberlinwohnen.de/wohnungsfinder/")
        self.formatter = MessageFormatter()

    async def send_welcome(self):
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text="🏠 *Flat Monitor Started*\n\n"
                     "I will notify you about new flats every minute!\n\n"
                     "Available commands:\n"
                     "• /list - Show all current flats\n"
                     "• /help - Show this help message",
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
                             "• /help - Show this help message",
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
        
        flats = await self.scraper.fetch_flats()
        
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
            initial_flats = await self.scraper.fetch_flats()
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
                current_flats = await self.scraper.fetch_flats()
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
