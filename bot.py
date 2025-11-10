# bot.py (Deployment-Ready Version)
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
from telegram.request import HTTPXRequest

# --- Configuration from Environment Variables ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

# --- Define a local download folder ---
# Render provides an ephemeral filesystem. This folder will be temporary.
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MAX_FILE_SIZE_BYTES = 1800 * 1024 * 1024  # 1.8 GB

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()] # Log to console (Render will capture this)
)
logger = logging.getLogger(__name__)

# --- Helper Functions (No changes needed here) ---
def get_filename_from_url(url: str) -> str:
    try:
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path)
        if filename:
            return filename
    except Exception as e:
        logger.warning(f"Could not extract filename from URL {url}: {e}")
    return f"downloaded_file_{int(datetime.now().timestamp())}"

async def progress_callback(downloaded: int, total: int, status_message: Message, last_update_time: dict):
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
    except Exception:
        pass

# --- Bot Command Handlers (No changes needed here) ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! I can download files from direct links and upload them to a channel.\n\n"
        "Usage:\n`/download <url> [optional_filename.ext]`",
        parse_mode=ParseMode.MARKDOWN
    )

async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/download <url> [filename]`", parse_mode=ParseMode.MARKDOWN)
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
                    await status_message.edit_text(f"❌ Error: File size exceeds the 1.8 GB limit.")
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
                chat_id=CHANNEL_ID, document=f, filename=filename,
                caption=f"Downloaded from: `{url}`", parse_mode=ParseMode.MARKDOWN
            )
        logger.info(f"Successfully uploaded {filename} from {url}")
        await status_message.edit_text("✅ Uploaded successfully!")
    except asyncio.TimeoutError:
        logger.error(f"TimeoutError for URL {url}")
        await status_message.edit_text("❌ Error: Download timed out. The server is too slow.")
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
    logger.error("Exception while handling an update:", exc_info=context.error)

# --- Main Bot Logic ---
def main():
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN environment variable not set. Exiting.")
        return
    if not CHANNEL_ID:
        logger.critical("CHANNEL_ID environment variable not set. Exiting.")
        return
    logger.info("Starting bot...")
    httpx_request = HTTPXRequest(pool_timeout=1800)
    application = Application.builder().token(BOT_TOKEN).request(httpx_request).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("download", download_command))
    application.add_error_handler(error_handler)
    application.run_polling()

if __name__ == "__main__":
    main()
