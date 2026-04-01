"""
Pinterest Video Downloader Telegram Bot
----------------------------------------
Requirements:
    pip install python-telegram-bot yt-dlp

Usage:
    1. Get a bot token from @BotFather on Telegram
    2. Set TELEGRAM_BOT_TOKEN (or BOT_TOKEN) as an env variable
    3. Run: python pinterest_bot.py
"""
from telegram.request import HTTPXRequest
import os
import asyncio
import sys
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
import logging
import tempfile

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import yt_dlp

# ─────────────────────────────────────────────
# CONFIG  ← set env vars instead of hardcoding secrets
# ─────────────────────────────────────────────
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")
PROXY_URL = os.getenv("PIN_PROXY_URL")

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def is_pinterest_url(url: str) -> bool:
    """Return True if the URL looks like a Pinterest link."""
    pinterest_domains = (
        "pinterest.com",
        "pinterest.co.uk",
        "pin.it",
        "www.pinterest",
    )
    return any(domain in url.lower() for domain in pinterest_domains)


def download_pinterest_video(url: str, output_dir: str) -> str | None:
    """
    Download the best-quality video from a Pinterest URL.
    Returns the file path on success, None on failure.
    yt-dlp fetches the original source video, so there is NO watermark.
    """
    output_template = os.path.join(output_dir, "%(id)s.%(ext)s")

    ydl_opts = {
        "format": "V_HLSV3_MOBILE-1299/V_HLSV3_MOBILE-808/V_HLSV3_MOBILE-523/best",
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "retries": 5,
        "socket_timeout": 30,
    }
    if PROXY_URL:
        ydl_opts["proxy"] = PROXY_URL

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # Resolve the actual filename
            filename = ydl.prepare_filename(info)
            # yt-dlp may change the extension after merge
            base = os.path.splitext(filename)[0]
            for ext in ("mp4", "mkv", "webm", "mov"):
                candidate = f"{base}.{ext}"
                if os.path.exists(candidate):
                    return candidate
            # Fallback: return whatever was written
            if os.path.exists(filename):
                return filename
    except yt_dlp.utils.DownloadError as e:
        logger.error("yt-dlp download error: %s", e)
    except Exception as e:
        logger.error("Unexpected error: %s", e)

    return None


# ─────────────────────────────────────────────
# HANDLERS
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome message."""
    text = (
        "👋 *Welcome to the Pinterest Video Downloader Bot!*\n\n"
        "📌 Just send me any Pinterest video link and I'll send back the "
        "clean MP4 — *no watermarks, no hassle*.\n\n"
        "Supports:\n"
        "• `pinterest.com` links\n"
        "• `pin.it` short links\n\n"
        "_Paste a link to get started!_"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Help message."""
    text = (
        "🆘 *How to use this bot*\n\n"
        "1. Open Pinterest and find a video Pin.\n"
        "2. Tap *Share → Copy Link*.\n"
        "3. Paste the link here.\n"
        "4. Receive your clean MP4!\n\n"
        "For issues, make sure the Pin actually contains a video."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main handler — download and send the video."""
    message = update.message
    text = (message.text or "").strip()

    # Basic URL check
    if not text.startswith("http"):
        await message.reply_text(
            "❓ Please send a valid Pinterest URL (starts with https://)."
        )
        return

    if not is_pinterest_url(text):
        await message.reply_text(
            "⚠️ That doesn't look like a Pinterest link.\n"
            "Please send a `pinterest.com` or `pin.it` URL.",
            parse_mode="Markdown",
        )
        return

    # Acknowledge
    status_msg = await message.reply_text("⏳ Downloading your video, please wait…")

    with tempfile.TemporaryDirectory() as tmpdir:
        loop = asyncio.get_event_loop()
        video_path = await loop.run_in_executor(
            None, download_pinterest_video, text, tmpdir
        )

        if not video_path:
            await status_msg.edit_text(
                "❌ Sorry, I couldn't download that video.\n\n"
                "Possible reasons:\n"
                "• The Pin is not a video (it may be an image or idea pin)\n"
                "• The Pin is private or deleted\n"
                "• Pinterest blocked the request — try again in a moment"
            )
            return

        file_size_mb = os.path.getsize(video_path) / (1024 * 1024)

        if file_size_mb > 50:
            await status_msg.edit_text(
                f"⚠️ Video is too large ({file_size_mb:.1f} MB).\n"
                "Telegram bots can only send files up to 50 MB."
            )
            return

        await status_msg.edit_text("📤 Uploading…")

        try:
            with open(video_path, "rb") as video_file:
                await message.reply_video(
                    video=video_file,
                    caption="✅ Here's your Pinterest video — no watermark!",
                    supports_streaming=True,
                )
            await status_msg.delete()
        except Exception as e:
            logger.error("Failed to send video: %s", e)
            await status_msg.edit_text(
                "❌ Failed to upload the video. Please try again."
            )
# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main() -> None:
    if not BOT_TOKEN:
        print("❌  Set TELEGRAM_BOT_TOKEN (or BOT_TOKEN) in your environment.")
        return

    request = HTTPXRequest(
        connect_timeout=30,
        read_timeout=60,
        write_timeout=60,
        pool_timeout=30,
    )

    app = Application.builder().token(BOT_TOKEN).request(request).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is running… Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
