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
                text="🏠 *Flat Monitor Started*\nI will notify you about new flats every minute!\nUse !list to see all current flats.",
                parse_mode="Markdown",
            )
            logger.info(f"Welcome message sent to chat {self.chat_id}")
        except TelegramError as e:
            logger.error(f"Failed to send welcome message: {e}")
            exit()

    def extract_flat_details(self, flat_element):
        """Extract detailed information about a flat."""
        try:
            # Get the flat ID
            flat_id = flat_element.get("id", "")

            # Extract title
            title = flat_element.find("h3")
            title_text = title.text.strip() if title else "No title"

            # Extract link
            link = (
                f"https://inberlinwohnen.de{title.find('a')['href']}"
                if title and title.find("a")
                else None
            )

            # Extract details from the table
            details = {}
            table = flat_element.find("table")
            if table:
                for row in table.find_all("tr"):
                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        key = cells[0].text.strip().rstrip(":")
                        value = cells[1].text.strip()
                        details[key] = value

            # Check WBS status
            wbs_required = details.get("WBS", "").lower() == "erforderlich"

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
                        soup = BeautifulSoup(html, "html.parser")
                        flats = []

                        # Find all flat listings
                        for flat in soup.find_all(
                            "div", id=lambda x: x and x.startswith("flat_")
                        ):
                            flat_details = self.extract_flat_details(flat)
                            if flat_details:
                                flats.append(flat_details)

                        logger.info(f"Found {len(flats)} flats")
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
            message = f"🏠 *New WBS Flats Available!* ({len(wbs_flats)})\n\n"
            for flat in wbs_flats:
                message += self.format_flat_message(flat) + "\n\n"

            try:
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
            message = f"✅ *New Non-WBS Flats Available!* ({len(non_wbs_flats)})\n\n"
            for flat in non_wbs_flats:
                message += self.format_flat_message(flat) + "\n\n"

            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                )
            except TelegramError as e:
                logger.error(f"Failed to send non-WBS update: {e}")

    async def handle_list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the !list command."""
        if str(update.effective_chat.id) != self.chat_id:
            return

        # Fetch latest flats
        flats = await self.fetch_flats()
        
        if not flats:
            await update.message.reply_text("No flats available at the moment.")
            return

        # Split flats into WBS and non-WBS
        wbs_flats = [f for f in flats if f["wbs_required"]]
        non_wbs_flats = [f for f in flats if not f["wbs_required"]]

        # Send WBS flats first
        if wbs_flats:
            message = f"🏠 *Current WBS Flats* ({len(wbs_flats)})\n\n"
            for flat in wbs_flats:
                message += self.format_flat_message(flat) + "\n\n"

            try:
                await update.message.reply_text(
                    text=message,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                )
            except TelegramError as e:
                logger.error(f"Failed to send WBS list: {e}")

        # Send non-WBS flats
        if non_wbs_flats:
            message = f"✅ *Current Non-WBS Flats* ({len(non_wbs_flats)})\n\n"
            for flat in non_wbs_flats:
                message += self.format_flat_message(flat) + "\n\n"

            try:
                await update.message.reply_text(
                    text=message,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                )
            except TelegramError as e:
                logger.error(f"Failed to send non-WBS list: {e}")

    async def monitor(self):
        """Monitor the website for new flats."""
        logger.info("Starting monitoring loop...")
        # Send welcome message when starting
        await self.send_welcome()

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

    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    monitor.application = application  # Store application reference

    # Add message handler for !list command
    application.add_handler(MessageHandler(
        filters.Regex(r'^!list$'),
        monitor.handle_list_command
    ))

    # Start the monitoring in the background
    monitoring_task = asyncio.create_task(monitor.monitor())
    
    # Start the bot
    await application.initialize()
    await application.start()
    
    try:
        # Run the bot until stopped
        await application.updater.start_polling()
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
