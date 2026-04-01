# Pinterest Video Downloader Telegram Bot

A simple Telegram bot that downloads Pinterest videos and sends the clean MP4 back to the user.

## Features

- Accepts `pinterest.com` and `pin.it` links
- Downloads the best available quality via `yt-dlp`
- Sends videos back through Telegram (up to 50 MB)

## Setup

1. Create a bot with `@BotFather` and copy the token.
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Set environment variables:
   ```
   TELEGRAM_BOT_TOKEN=your_token_here
   # Optional
   PIN_PROXY_URL=socks5://user:pass@host:port
   ```

## Run

```
python pinterest_bot.py
```

## Security Notes

- Never commit your bot token or proxy credentials.
- Use environment variables (see `.env.example`).
- Rotate tokens immediately if exposed.

## License

Add a license if you intend to open-source this project.
