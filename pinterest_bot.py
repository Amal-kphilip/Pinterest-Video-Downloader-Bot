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
from urllib import request as urlrequest
import re

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BotCommand,
    MenuButtonCommands,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import yt_dlp

# ─────────────────────────────────────────────
# CONFIG  ← set env vars instead of hardcoding secrets
# ─────────────────────────────────────────────
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# UI / MENU
# ─────────────────────────────────────────────
MENU_DOWNLOAD = "📌 Download Video"
MENU_HELP = "❓ Help"
MENU_ABOUT = "ℹ️ About"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(MENU_DOWNLOAD)],
        [KeyboardButton(MENU_HELP), KeyboardButton(MENU_ABOUT)],
    ],
    resize_keyboard=True,
)

QUALITY_FORMATS = {
    # Primary format per quality, with fallback to next best quality
    "360": ["V_HLSV3_MOBILE-523"],
    "540": ["V_HLSV3_MOBILE-808", "V_HLSV3_MOBILE-523"],
    "720": ["V_HLSV3_MOBILE-1299", "V_HLSV3_MOBILE-808", "V_HLSV3_MOBILE-523"],
}

QUALITY_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("📱 360p", callback_data="q:360"),
            InlineKeyboardButton("📺 540p", callback_data="q:540"),
            InlineKeyboardButton("🎬 720p", callback_data="q:720"),
        ]
    ]
)

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
        "pinimg.com",
    )
    return any(domain in url.lower() for domain in pinterest_domains)


def download_pinterest_video(
    url: str, output_dir: str, format_chain: list[str]
) -> tuple[str | None, str | None]:
    """
    Download the best-quality video from a Pinterest URL.
    Returns (file path, format used) on success, (None, None) on failure.
    yt-dlp fetches the original source video, so there is NO watermark.
    """
    output_template = os.path.join(output_dir, "%(id)s.%(ext)s")
    # Final fallback for pins that don't expose the mobile format IDs
    format_chain = format_chain + ["bestvideo*/best"]

    for fmt in format_chain:
        ydl_opts = {
            # Video-only, with quality fallback
            "format": fmt,
            "outtmpl": output_template,
            "quiet": True,
            "no_warnings": True,
            "retries": 5,
            "socket_timeout": 30,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
        }
        try:
            logger.info("Trying format: %s", fmt)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                # Resolve the actual filename
                filename = ydl.prepare_filename(info)
                # yt-dlp may change the extension after merge
                base = os.path.splitext(filename)[0]
                for ext in ("mp4", "mkv", "webm", "mov"):
                    candidate = f"{base}.{ext}"
                    if os.path.exists(candidate):
                        return candidate, fmt
                # Fallback: return whatever was written
                if os.path.exists(filename):
                    return filename, fmt
        except yt_dlp.utils.DownloadError as e:
            msg = str(e)
            if "Requested format is not available" in msg:
                logger.info("Format unavailable: %s", fmt)
                continue
            logger.error("yt-dlp download error: %s", e)
            return None, None
        except Exception as e:
            logger.error("Unexpected error: %s", e)
            return None, None

    return None, None


def expand_url(url: str) -> str:
    """Resolve short links (like pin.it) to their final URL."""
    if not url.lower().startswith("http"):
        return url
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        req = urlrequest.Request(url, headers=headers, method="HEAD")
        with urlrequest.urlopen(req, timeout=10) as resp:
            return resp.geturl()
    except Exception:
        try:
            req = urlrequest.Request(url, headers=headers, method="GET")
            with urlrequest.urlopen(req, timeout=10) as resp:
                return resp.geturl()
        except Exception as e:
            logger.warning("Failed to expand URL %s: %s", url, e)
            return url


def extract_urls(text: str) -> list[str]:
    """Extract URLs from text."""
    return re.findall(r"https?://\S+", text)


# ─────────────────────────────────────────────
# HANDLERS
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome message."""
    text = (
        "👋 *Welcome to the Pinterest Video Downloader Bot!*\n\n"
        "*What can this bot do?*\n"
        "• Download Pinterest videos with no watermark\n"
        "• Accept `pinterest.com` and `pin.it` links\n"
        "• Send the video back instantly (up to 50 MB)\n\n"
        "*Batch download*\n"
        "• Send up to 5 links in one message (one per line)\n"
        "• Pick quality once and I’ll download them one by one\n\n"
        "Tap a button below or paste a link to get started."
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Help message."""
    text = (
        "🆘 *How to use this bot*\n\n"
        "1. Open Pinterest and find a video Pin.\n"
        "2. Tap *Share → Copy Link*.\n"
        "3. Paste the link here.\n"
        "4. Receive your clean MP4!\n\n"
        "*Batch download (up to 5 links)*\n"
        "• Send multiple Pinterest links in one message, one per line.\n"
        "• Choose a quality once, and I’ll download them sequentially.\n\n"
        "For issues, make sure the Pin actually contains a video."
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """About message."""
    text = (
        "ℹ️ *About this bot*\n\n"
        "Send a Pinterest video link and I’ll fetch the best available quality "
        "and deliver it here. Video-only output is enabled.\n\n"
        "Tip: If a link fails, try another pin or wait a moment."
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main handler — download and send the video."""
    message = update.message
    text = (message.text or "").strip()

    # Menu buttons
    if text == MENU_DOWNLOAD:
        await message.reply_text(
            "📌 Send me a Pinterest video link (starts with https://).",
            reply_markup=MAIN_KEYBOARD,
        )
        return
    if text == MENU_HELP:
        await help_command(update, context)
        return
    if text == MENU_ABOUT:
        await about_command(update, context)
        return

    urls = extract_urls(text)
    if not urls:
        await message.reply_text(
            "❓ Please send a valid Pinterest URL (starts with https://).",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    pinterest_urls = [u for u in urls if is_pinterest_url(u)]
    if not pinterest_urls:
        await message.reply_text(
            "⚠️ That doesn't look like a Pinterest link.\n"
            "Please send a `pinterest.com` or `pin.it` URL.",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    if len(pinterest_urls) > 5:
        await message.reply_text(
            "⚠️ You can send up to 5 links at a time. I’ll process the first 5.",
            reply_markup=MAIN_KEYBOARD,
        )
        pinterest_urls = pinterest_urls[:5]

    context.user_data["pending_urls"] = pinterest_urls
    await message.reply_text(
        f"Select a quality for {len(pinterest_urls)} video(s):",
        reply_markup=QUALITY_KEYBOARD,
    )
    return


async def quality_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle quality selection and download batch."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data or ""
    quality = data.split(":")[1] if ":" in data else None
    if quality not in QUALITY_FORMATS:
        await query.edit_message_text("⚠️ Invalid quality selection. Please try again.")
        return

    urls = context.user_data.get("pending_urls") or []
    if not urls:
        await query.edit_message_text("⚠️ No pending downloads. Send a link again.")
        return

    format_chain = QUALITY_FORMATS[quality]
    await query.edit_message_text(f"✅ Selected {quality}p. Starting downloads…")

    # Process each URL sequentially
    with tempfile.TemporaryDirectory() as tmpdir:
        loop = asyncio.get_event_loop()
        total = len(urls)
        for idx, url in enumerate(urls, start=1):
            logger.info("Downloading %s/%s | quality=%sp | url=%s", idx, total, quality, url)
            status_msg = await query.message.reply_text(
                f"⏳ Downloading video {idx} of {total}…"
            )
            resolved_url = await loop.run_in_executor(None, expand_url, url)
            video_path, used_fmt = await loop.run_in_executor(
                None, download_pinterest_video, resolved_url, tmpdir, format_chain
            )

            if not video_path:
                logger.warning("Failed download %s/%s | url=%s", idx, total, url)
                await status_msg.edit_text(
                    f"❌ Failed to download video {idx} of {total}.\n{url}"
                )
                continue
            logger.info("Downloaded with format: %s", used_fmt)
            # Ensure file timestamp is current
            try:
                os.utime(video_path, None)
            except Exception as e:
                logger.warning("Failed to update file timestamp: %s", e)

            file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
            if file_size_mb > 50:
                await status_msg.edit_text(
                    f"⚠️ Video {idx} is too large ({file_size_mb:.1f} MB).\n"
                    "Telegram bots can only send files up to 50 MB."
                )
                continue

            await status_msg.edit_text("📤 Sending your video…")

            try:
                with open(video_path, "rb") as video_file:
                    await query.message.reply_video(
                        video=video_file,
                        caption="✅ Here's your Pinterest video — no watermark!",
                        supports_streaming=True,
                    )
                await status_msg.delete()
                logger.info("Sent video %s/%s", idx, total)
            except Exception as e:
                logger.error("Failed to send video %s/%s: %s", idx, total, e)
                await status_msg.edit_text(
                    f"❌ Failed to upload video {idx}. Please try again."
                )

    context.user_data["pending_urls"] = []


async def post_init(app: Application) -> None:
    """Set bot commands and menu button."""
    try:
        await app.bot.set_my_commands(
            [
                BotCommand("start", "Show welcome message"),
                BotCommand("help", "How to use the bot"),
                BotCommand("about", "About this bot"),
                BotCommand("menu", "Show menu buttons"),
            ]
        )
        await app.bot.set_my_short_description("Download Pinterest videos instantly.")
        await app.bot.set_my_description(
            "Send a Pinterest video link and receive a clean, video-only MP4. "
            "Supports pinterest.com and pin.it links."
        )
        await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except Exception as e:
        logger.warning("Failed to set bot profile info: %s", e)
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

    app = Application.builder().token(BOT_TOKEN).request(request).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(CallbackQueryHandler(quality_callback, pattern=r"^q:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is running… Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
