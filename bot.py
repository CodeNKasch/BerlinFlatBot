import asyncio
import logging
import json
from datetime import datetime

import aiohttp
from bs4 import BeautifulSoup
from telegram import Bot, Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


class FlatMonitor:
    def __init__(self, bot_token, chat_id):
        """Initialize the monitor with bot token and chat ID."""
        self.bot = Bot(token=bot_token)
        self.chat_id = chat_id
        self.last_flats = set()
        self.url = "https://inberlinwohnen.de/wohnungsfinder/"
        self.current_flats = []  # Store current flats
        self.application = None  # Store application reference
        logger.info("FlatMonitor initialized")

    async def send_welcome(self):
        """Send welcome message to the chat."""
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
            logger.error(f"Failed to send welcome message: {e}")
            exit()

    async def handle_help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /help command."""
        if str(update.effective_chat.id) != self.chat_id:
            return

        help_text = (
            "🏠 *Berlin Flat Monitor Help*\n\n"
            "I monitor inberlinwohnen.de for new flats and notify you when they appear.\n\n"
            "*Available Commands:*\n"
            "• /list - Show all current flats\n"
            "• /help - Show this help message\n\n"
            "The bot will automatically notify you about:\n"
            "• New WBS flats 🏠\n"
            "• New non-WBS flats ✅"
        )

        try:
            await update.message.reply_text(
                text=help_text,
                parse_mode="Markdown",
            )
            logger.info("Help message sent")
        except TelegramError as e:
            logger.error(f"Failed to send help message: {e}")

    def extract_flat_details(self, flat_element):
        """Extract detailed information about a flat."""
        try:
            # Get the flat ID
            flat_id = flat_element.get("id", "")
            logger.debug(f"Processing flat with ID: {flat_id}")

            # Extract title from h2
            title = flat_element.find("h2")
            title_text = title.text.strip() if title else "No title"
            logger.debug(f"Found title: {title_text}")

            # Extract link
            link = None
            link_element = flat_element.find("a", class_="org-but")
            if link_element:
                link = link_element["href"]
                if not link.startswith("http"):
                    link = f"https://inberlinwohnen.de{link}"
                logger.debug(f"Found link: {link}")

            # Extract details from the tables
            details = {}
            
            # Find all tables in the flat element
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

            # Extract features from the hackerl spans
            features = []
            feature_spans = flat_element.find_all("span", class_="hackerl")
            for span in feature_spans:
                features.append(span.text.strip())
            if features:
                details["Features"] = ", ".join(features)

            # Check WBS status - not present in the example, but keeping the logic
            wbs_required = False
            wbs_text = details.get("WBS", "").lower()
            if "erforderlich" in wbs_text or "wbs" in wbs_text:
                wbs_required = True
            logger.debug(f"WBS required: {wbs_required}")

            return {
                "id": flat_id,
                "title": title_text,
                "link": link,
                "details": details,
                "wbs_required": wbs_required,
            }
        except Exception as e:
            logger.error(f"Error extracting flat details: {e}")
            return None

    async def fetch_flats(self):
        """Fetch current flats from the website."""
        logger.info("Fetching flats from website...")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.url) as response:
                    if response.status == 200:
                        html = await response.text()
                        logger.info(f"Received HTML response of length: {len(html)}")
                        
                        soup = BeautifulSoup(html, "html.parser")
                        flats = []

                        # Find all flat listings by looking for li elements with id starting with "flat_"
                        flat_elements = soup.find_all("li", id=lambda x: x and x.startswith("flat_"))
                        logger.info(f"Found {len(flat_elements)} flat elements in HTML")

                        for flat in flat_elements:
                            flat_details = self.extract_flat_details(flat)
                            if flat_details:
                                flats.append(flat_details)
                            else:
                                logger.warning(f"Failed to extract details for flat element: {flat.get('id', 'unknown')}")

                        logger.info(f"Successfully parsed {len(flats)} flats")
                        self.current_flats = flats  # Store the current flats
                        return flats
                    else:
                        logger.error(
                            f"Failed to fetch flats. Status code: {response.status}"
                        )
                        return []
        except Exception as e:
            logger.error(f"Error fetching flats: {e}")
            return []

    def format_flat_message(self, flat):
        """Format a single flat's details into a message."""
        details = flat["details"]
        message = f"*{flat['title']}*\n"

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
            if key in details:
                message += f"• {key}: {details[key]}\n"

        # Add link
        if flat["link"]:
            message += f"\n[View Details]({flat['link']})"

        return message

    async def send_update(self, new_flats):
        """Send update message to Telegram chat."""
        if not new_flats:
            return

        # Split flats into WBS and non-WBS
        wbs_flats = [f for f in new_flats if f["wbs_required"]]
        non_wbs_flats = [f for f in new_flats if not f["wbs_required"]]

        # Send WBS flats first
        if wbs_flats:
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=f"🏠 *New WBS Flats Available!* ({len(wbs_flats)})",
                    parse_mode="Markdown",
                )
                for flat in wbs_flats:
                    message = self.format_flat_message(flat)
                    await self.bot.send_message(
                        chat_id=self.chat_id,
                        text=message,
                        parse_mode="Markdown",
                        disable_web_page_preview=True,
                    )
            except TelegramError as e:
                logger.error(f"Failed to send WBS update: {e}")

        # Send non-WBS flats
        if non_wbs_flats:
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=f"✅ *New Non-WBS Flats Available!* ({len(non_wbs_flats)})",
                    parse_mode="Markdown",
                )
                for flat in non_wbs_flats:
                    message = self.format_flat_message(flat)
                    await self.bot.send_message(
                        chat_id=self.chat_id,
                        text=message,
                        parse_mode="Markdown",
                        disable_web_page_preview=True,
                    )
            except TelegramError as e:
                logger.error(f"Failed to send non-WBS update: {e}")

    async def handle_list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /list command."""
        logger.info(f"Received command: {update.message.text}")
        logger.info(f"Chat ID: {update.effective_chat.id}")
        logger.info(f"Expected Chat ID: {self.chat_id}")
        
        if str(update.effective_chat.id) != self.chat_id:
            logger.info("Message not from target chat, ignoring")
            return

        logger.info("Processing list command")
        
        # Fetch latest flats
        flats = await self.fetch_flats()
        
        if not flats:
            await update.message.reply_text("No flats available at the moment.")
            return

        # Split flats into WBS and non-WBS
        wbs_flats = [f for f in flats if f["wbs_required"]]
        non_wbs_flats = [f for f in flats if not f["wbs_required"]]

        # Send WBS flats first (limited to 5)
        if wbs_flats:
            try:
                total_wbs = len(wbs_flats)
                wbs_flats = wbs_flats[:5]  # Limit to 5 flats
                await update.message.reply_text(
                    text=f"🏠 *Current WBS Flats* (Showing 5 of {total_wbs})",
                    parse_mode="Markdown",
                )
                for flat in wbs_flats:
                    message = self.format_flat_message(flat)
                    await update.message.reply_text(
                        text=message,
                        parse_mode="Markdown",
                        disable_web_page_preview=True,
                    )
                logger.info(f"Sent {len(wbs_flats)} WBS flats")
            except TelegramError as e:
                logger.error(f"Failed to send WBS list: {e}")

        # Send non-WBS flats (limited to 5)
        if non_wbs_flats:
            try:
                total_non_wbs = len(non_wbs_flats)
                non_wbs_flats = non_wbs_flats[:5]  # Limit to 5 flats
                await update.message.reply_text(
                    text=f"✅ *Current Non-WBS Flats* (Showing 5 of {total_non_wbs})",
                    parse_mode="Markdown",
                )
                for flat in non_wbs_flats:
                    message = self.format_flat_message(flat)
                    await update.message.reply_text(
                        text=message,
                        parse_mode="Markdown",
                        disable_web_page_preview=True,
                    )
                logger.info(f"Sent {len(non_wbs_flats)} non-WBS flats")
            except TelegramError as e:
                logger.error(f"Failed to send non-WBS list: {e}")

    async def monitor(self):
        """Monitor the website for new flats."""
        logger.info("Starting monitoring loop...")
        # Send welcome message when starting
        await self.send_welcome()

        # Initialize last_flats with current flats to avoid sending all flats as new
        initial_flats = await self.fetch_flats()
        self.last_flats = {flat["id"] for flat in initial_flats}
        logger.info(f"Initialized with {len(self.last_flats)} existing flats")

        while True:
            try:
                logger.info("Checking for new flats...")
                current_flats = await self.fetch_flats()
                current_flat_set = {flat["id"] for flat in current_flats}

                # Find new flats
                new_flats = []
                for flat in current_flats:
                    if flat["id"] not in self.last_flats:
                        new_flats.append(flat)

                if new_flats:
                    logger.info(f"Found {len(new_flats)} new flats")
                    await self.send_update(new_flats)
                else:
                    logger.info("No new flats found")

                self.last_flats = current_flat_set

            except Exception as e:
                logger.error(f"Error during monitoring: {e}")

            logger.info("Waiting 60 seconds before next check...")
            await asyncio.sleep(60)


async def main():
    # Load configuration from config.json
    with open('config.json', 'r') as f:
        config = json.load(f)
    
    BOT_TOKEN = config['BOT_TOKEN']
    CHAT_ID = config['CHAT_ID']
    
    logger.info("Starting bot...")
    monitor = FlatMonitor(BOT_TOKEN, CHAT_ID)

    # Create application with proper update settings
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )
    monitor.application = application  # Store application reference

    # Add command handlers
    application.add_handler(CommandHandler("list", monitor.handle_list_command))
    application.add_handler(CommandHandler("help", monitor.handle_help_command))

    # Start the monitoring in the background
    monitoring_task = asyncio.create_task(monitor.monitor())
    
    # Start the bot
    await application.initialize()
    await application.start()
    
    try:
        # Run the bot until stopped
        logger.info("Starting polling...")
        await application.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        logger.info("Polling started successfully")
        
        # Keep the bot running
        while True:
            await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"Error during polling: {e}")
    finally:
        # Clean up
        monitoring_task.cancel()
        try:
            await monitoring_task
        except asyncio.CancelledError:
            pass
        await application.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot stopped due to error: {e}")
