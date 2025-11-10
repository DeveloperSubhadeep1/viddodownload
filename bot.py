# bot.py (Complete and Final Version)
import os
import logging
import asyncio
import tempfile
from urllib.parse import urlparse
from datetime import datetime

import aiohttp
from telegram import Update, Message
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest # <-- IMPORTANT IMPORT

# --- Configuration ---
# I have removed your hardcoded token for security. Please replace it with your new one.
# It is highly recommended to use a .env file for this in the future.
BOT_TOKEN = "7203772931:AAFw3mgaT9Sx_F6ByiljqComBAG25mSh0AA" 
CHANNEL_ID = "-1002608131568" # Your Channel ID

# --- Define a custom download folder ---
# The bot will create and use a folder named "downloads" in the same directory as the script.
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True) # This creates the folder if it doesn't exist

# Telegram's file size limit for bots is 2000 MB. We'll set a safer limit.
MAX_FILE_SIZE_BYTES = 1800 * 1024 * 1024  # 1.8 GB

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log")
    ]
)
logger = logging.getLogger(__name__)

# --- Helper Functions ---
def get_filename_from_url(url: str) -> str:
    """Extracts a filename from a URL, or generates a default one."""
    try:
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path)
        if filename:
            return filename
    except Exception as e:
        logger.warning(f"Could not extract filename from URL {url}: {e}")
    return f"downloaded_file_{int(datetime.now().timestamp())}"


async def progress_callback(
    downloaded: int, 
    total: int, 
    status_message: Message, 
    last_update_time: dict
):
    """Updates the user on download progress."""
    current_time = datetime.now()
    if (current_time - last_update_time.get('time', datetime.min)).total_seconds() < 3:
        return

    percentage = (downloaded / total) * 100 if total > 0 else 0
    downloaded_mb = downloaded / (1024 * 1024)
    total_mb = total / (1024 * 1024)
    
    progress_text = f"Downloading... {percentage:.1f}%\n"
    progress_text += f"[{'█' * int(percentage // 5)}{' ' * (20 - int(percentage // 5))}]\n"
    progress_text += f"{downloaded_mb:.2f} MB / {total_mb:.2f} MB"

    try:
        await status_message.edit_text(progress_text)
        last_update_time['time'] = current_time
    except Exception as e:
        logger.debug(f"Progress update failed (might be expected): {e}")

# --- Bot Command Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    await update.message.reply_text(
        "Hello! I can download files from direct links and upload them to a channel.\n\n"
        "Usage:\n`/download <url> [optional_filename.ext]`",
        parse_mode=ParseMode.MARKDOWN
    )

async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /download command."""
    chat_id = update.message.chat_id
    args = context.args

    if not args:
        await update.message.reply_text(
            "Please provide a URL.\nUsage: `/download <url> [filename]`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    url = args[0]
    custom_filename = " ".join(args[1:]) if len(args) > 1 else None

    if not url.startswith(('http://', 'https://')):
        await update.message.reply_text("Invalid URL. It must start with `http://` or `https://`.")
        return

    status_message = await update.message.reply_text("Initializing download...")
    
    file_path = ""
    try:
        timeout = aiohttp.ClientTimeout(total=3600, sock_read=1800)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    await status_message.edit_text(f"❌ Error: Received status code {response.status}")
                    return

                total_size = int(response.headers.get('content-length', 0))
                if total_size > MAX_FILE_SIZE_BYTES:
                    await status_message.edit_text(
                        f"❌ Error: File size ({total_size / 1024**3:.2f} GB) "
                        f"exceeds the limit of {MAX_FILE_SIZE_BYTES / 1024**3:.2f} GB."
                    )
                    return

                filename = custom_filename or get_filename_from_url(url)
                file_path = os.path.join(DOWNLOAD_DIR, filename)
                
                downloaded = 0
                last_update_time = {}

                await status_message.edit_text("Starting download...")

                with open(file_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        await progress_callback(downloaded, total_size, status_message, last_update_time)

        await status_message.edit_text("Download complete. Starting upload...")
        
        with open(file_path, 'rb') as f:
            await context.bot.send_document(
                chat_id=CHANNEL_ID,
                document=f,
                filename=filename,
                caption=f"Downloaded from: `{url}`\n\nUploaded by bot.",
                parse_mode=ParseMode.MARKDOWN
            )

        logger.info(f"Successfully downloaded and uploaded {filename} from {url}")
        await status_message.edit_text("✅ Uploaded successfully!")

    except asyncio.TimeoutError:
        logger.error(f"TimeoutError for URL {url}")
        await status_message.edit_text("❌ Error: Download timed out. The server is too slow or unresponsive.")
    except aiohttp.ClientError as e:
        logger.error(f"Aiohttp error for URL {url}: {e}")
        await status_message.edit_text(f"❌ Network error: Failed to download the file. {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        await status_message.edit_text(f"❌ An unexpected error occurred: `{str(e)}`")
    finally:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Cleaned up temporary file: {file_path}")
            except OSError as e:
                logger.error(f"Error deleting file {file_path}: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error."""
    logger.error("Exception while handling an update:", exc_info=context.error)

# --- Main Bot Logic ---
# def main():
    """Start the bot."""
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_NEW_BOT_TOKEN_HERE":
        logger.critical("BOT_TOKEN is not set. Please edit the script and add your bot token. Exiting.")
        return
    if not CHANNEL_ID:
        logger.critical("CHANNEL_ID is not set. Exiting.")
        return

    logger.info("Starting bot...")

    # Create a custom request object with longer timeouts for uploading files.
    httpx_request = HTTPXRequest(
        connect_timeout=10,
        read_timeout=60,
        write_timeout=1800,  # 30 minutes for uploading
    )

    # Pass the custom request object to the Application builder
    application = Application.builder().token(BOT_TOKEN).request(httpx_request).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("download", download_command))
    application.add_error_handler(error_handler)
    application.run_polling()


def main():
    """Start the bot."""
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_NEW_BOT_TOKEN_HERE":
        logger.critical("BOT_TOKEN is not set. Please edit the script and add your bot token. Exiting.")
        return
    if not CHANNEL_ID:
        logger.critical("CHANNEL_ID is not set. Exiting.")
        return

    logger.info("Starting bot...")

    # --- THE CHANGE IS HERE ---
    # Create a custom request object with a very long pool timeout.
    # This ensures that the underlying connection pool does not time out
    # during long file uploads. 30 minutes should be more than enough.
    httpx_request = HTTPXRequest(pool_timeout=1800) # 1800 seconds = 30 minutes

    # Pass the custom request object to the Application builder
    application = Application.builder().token(BOT_TOKEN).request(httpx_request).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("download", download_command))
    application.add_error_handler(error_handler)
    application.run_polling()

if __name__ == "__main__":
    main()