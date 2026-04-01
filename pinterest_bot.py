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
import html
import io

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
import requests
import cv2
import numpy as np
from PIL import Image

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
MENU_UPSCALE = "🔍 Upscale Image"
MENU_HELP = "❓ Help"
MENU_ABOUT = "ℹ️ About"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(MENU_DOWNLOAD), KeyboardButton(MENU_UPSCALE)],
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

UPSCALE_PROMPT_KEYBOARD = InlineKeyboardMarkup(
    [[InlineKeyboardButton("🔍 Upscale Image", callback_data="up:prompt")]]
)

UPSCALE_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("2x", callback_data="upscale:2"),
            InlineKeyboardButton("3x", callback_data="upscale:3"),
            InlineKeyboardButton("4x", callback_data="upscale:4"),
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


def is_image_url(url: str) -> bool:
    """Return True if the URL ends with a supported image extension."""
    cleaned = url.split("?")[0].lower()
    return cleaned.endswith((".jpg", ".jpeg", ".png", ".webp"))


def _oembed_image_url(pin_url: str) -> str | None:
    """Try Pinterest oEmbed to get a thumbnail image URL."""
    try:
        oembed_url = "https://www.pinterest.com/oembed.json"
        resp = requests.get(oembed_url, params={"url": pin_url}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        thumb = data.get("thumbnail_url")
        if thumb:
            return thumb
    except Exception as e:
        logger.info("oEmbed lookup failed: %s", e)
    return None


def detect_pinterest_image(pin_url: str, allow_thumbnail: bool = False) -> str | None:
    """
    Detect if a Pinterest URL is an image pin.
    Returns a direct image URL when possible, otherwise None.
    """
    if is_image_url(pin_url):
        return pin_url
    if "pinimg.com" in pin_url:
        return pin_url
    if allow_thumbnail:
        oembed_img = _oembed_image_url(pin_url)
        if oembed_img:
            return oembed_img
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(pin_url, headers=headers, timeout=10)
        resp.raise_for_status()
        page = resp.text
    except Exception as e:
        logger.warning("Failed to fetch pin page: %s", e)
        if allow_thumbnail:
            return _oembed_image_url(pin_url)
        return None

    # If video metadata exists, treat it as a video pin
    if re.search(r'property="og:video', page):
        return None

    match = re.search(r'property="og:image"\s+content="([^"]+)"', page)
    if not match:
        match = re.search(r'name="og:image"\s+content="([^"]+)"', page)
    if match:
        return html.unescape(match.group(1))
    if allow_thumbnail:
        return _oembed_image_url(pin_url)
    return None


def upscale_image_bytes(image_bytes: bytes, scale: int) -> tuple[bytes | None, tuple[int, int] | None, tuple[int, int] | None, str | None, str | None]:
    """
    Upscale an image using OpenCV Lanczos interpolation.
    Returns (bytes, original_size, new_size, ext, error).
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
    except Exception as e:
        return None, None, None, None, f"Failed to open image: {e}"

    fmt = (img.format or "").upper()
    if fmt == "JPG":
        fmt = "JPEG"
    if fmt not in {"JPEG", "PNG", "WEBP"}:
        return None, None, None, None, "Unsupported image format."

    orig_w, orig_h = img.size
    if orig_w > 3000:
        return None, (orig_w, orig_h), None, None, "Image is already large."

    # Preserve alpha if present
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    if has_alpha:
        img = img.convert("RGBA")
        np_img = np.array(img)
        cv_img = cv2.cvtColor(np_img, cv2.COLOR_RGBA2BGRA)
    else:
        img = img.convert("RGB")
        np_img = np.array(img)
        cv_img = cv2.cvtColor(np_img, cv2.COLOR_RGB2BGR)

    new_w, new_h = orig_w * scale, orig_h * scale
    resized = cv2.resize(cv_img, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

    if has_alpha:
        rgb_img = cv2.cvtColor(resized, cv2.COLOR_BGRA2RGBA)
        out_img = Image.fromarray(rgb_img, mode="RGBA")
    else:
        rgb_img = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        out_img = Image.fromarray(rgb_img, mode="RGB")

    buf = io.BytesIO()
    ext = "png" if fmt == "PNG" else "webp" if fmt == "WEBP" else "jpg"
    if fmt == "JPEG":
        out_img = out_img.convert("RGB")
        out_img.save(buf, format="JPEG", quality=95)
    elif fmt == "PNG":
        out_img.save(buf, format="PNG", optimize=True)
    else:
        out_img.save(buf, format="WEBP", quality=95, method=6)
    return buf.getvalue(), (orig_w, orig_h), (new_w, new_h), ext, None


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
        "*Image upscaling*\n"
        "• Detects image pins and lets you upscale 2x/3x/4x\n\n"
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
        "*Image upscaling*\n"
        "• Send a Pinterest image link and tap *Upscale Image*, or\n"
        "• Use `/upscale <image url>` and choose 2x/3x/4x.\n\n"
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


async def upscale_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Upscale a Pinterest image via /upscale <url>."""
    message = update.message
    if not context.args:
        await message.reply_text(
            "Usage: /upscale <pinterest image url>",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    url = context.args[0].strip()
    if not url.startswith("http"):
        await message.reply_text(
            "❓ Please provide a valid URL (starts with https://).",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    loop = asyncio.get_event_loop()
    resolved_url = await loop.run_in_executor(None, expand_url, url)
    image_url = await loop.run_in_executor(None, detect_pinterest_image, resolved_url, True)
    if not image_url:
        await message.reply_text(
            "⚠️ That link doesn’t look like an image pin.\n"
            "Send a Pinterest image URL to upscale.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    context.user_data["pending_image_url"] = image_url
    await message.reply_text(
        "Select upscale factor (default 2x):",
        reply_markup=UPSCALE_KEYBOARD,
    )


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
    if text == MENU_UPSCALE:
        await message.reply_text(
            "🔍 Send a Pinterest image link to upscale (or use `/upscale <url>`).",
            parse_mode="Markdown",
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

    # If a single URL points to an image pin, offer upscale option
    if len(pinterest_urls) == 1:
        loop = asyncio.get_event_loop()
        resolved_url = await loop.run_in_executor(None, expand_url, pinterest_urls[0])
        image_url = await loop.run_in_executor(None, detect_pinterest_image, resolved_url, True)
        if image_url:
            context.user_data["pending_image_url"] = image_url
            await message.reply_text(
                "🖼️ I found an image pin. Want to upscale it?",
                reply_markup=UPSCALE_PROMPT_KEYBOARD,
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


async def upscale_prompt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show upscale options after image detection."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    image_url = context.user_data.get("pending_image_url")
    if not image_url:
        await query.edit_message_text("⚠️ No image to upscale. Send a link again.")
        return

    await query.edit_message_text(
        "Select upscale factor (default 2x):",
        reply_markup=UPSCALE_KEYBOARD,
    )


async def upscale_scale_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle upscale factor selection."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data or ""
    scale_str = data.split(":")[1] if ":" in data else ""
    if scale_str not in {"2", "3", "4"}:
        await query.edit_message_text("⚠️ Invalid upscale option.")
        return
    scale = int(scale_str)

    image_url = context.user_data.get("pending_image_url")
    if not image_url:
        await query.edit_message_text("⚠️ No image to upscale. Send a link again.")
        return

    logger.info("Upscaling image | scale=%sx | url=%s", scale, image_url)
    await query.edit_message_text(f"⏳ Upscaling {scale}x…")

    def _download_and_upscale() -> tuple[bytes | None, tuple[int, int] | None, tuple[int, int] | None, str | None, str | None]:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(image_url, headers=headers, timeout=20)
        resp.raise_for_status()
        return upscale_image_bytes(resp.content, scale)

    loop = asyncio.get_event_loop()
    try:
        img_bytes, orig_size, new_size, ext, err = await loop.run_in_executor(
            None, _download_and_upscale
        )
    except Exception as e:
        logger.error("Upscale failed: %s", e)
        await query.edit_message_text("❌ Failed to upscale image. Please try again.")
        return

    if err:
        if err == "Image is already large." and orig_size:
            await query.edit_message_text(
                f"⚠️ Image is already large ({orig_size[0]}x{orig_size[1]}). Upscaling skipped."
            )
        else:
            await query.edit_message_text(f"❌ {err}")
        return

    if not img_bytes or not orig_size or not new_size or not ext:
        await query.edit_message_text("❌ Failed to upscale image.")
        return

    caption = f"✅ Upscaled from {orig_size[0]}x{orig_size[1]} → {new_size[0]}x{new_size[1]}"
    bio = io.BytesIO(img_bytes)
    bio.name = f"upscaled_{scale}x.{ext}"

    await query.message.reply_document(
        document=bio,
        caption=caption,
        filename=bio.name,
    )
    await query.edit_message_text("✅ Done.")
    context.user_data["pending_image_url"] = None


async def post_init(app: Application) -> None:
    """Set bot commands and menu button."""
    try:
        await app.bot.set_my_commands(
            [
                BotCommand("start", "Show welcome message"),
                BotCommand("help", "How to use the bot"),
                BotCommand("about", "About this bot"),
                BotCommand("menu", "Show menu buttons"),
                BotCommand("upscale", "Upscale a Pinterest image"),
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
    app.add_handler(CommandHandler("upscale", upscale_command))
    app.add_handler(CallbackQueryHandler(quality_callback, pattern=r"^q:"))
    app.add_handler(CallbackQueryHandler(upscale_prompt_callback, pattern=r"^up:prompt$"))
    app.add_handler(CallbackQueryHandler(upscale_scale_callback, pattern=r"^upscale:\d+$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is running… Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
