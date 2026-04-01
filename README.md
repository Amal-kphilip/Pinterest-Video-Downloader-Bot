# Pinterest Video Downloader Telegram Bot

A simple Telegram bot that downloads Pinterest videos and sends the clean MP4 back to the user.

## Features

- Accepts `pinterest.com` and `pin.it` links
- Downloads the best available quality via `yt-dlp`
- Lets users pick 360p / 540p / 720p
- Supports batch downloads (up to 5 links at once)
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
   ```

## Run

```
python pinterest_bot.py
```

## Deploy on Railway

1. Create a new project and connect your GitHub repo.
2. Set environment variables in Railway:
   - `TELEGRAM_BOT_TOKEN`
3. Deploy. Railway will run the worker using the `Procfile` or `nixpacks.toml`.

## Security Notes

- Never commit your bot token or proxy credentials.
- Use environment variables (see `.env.example`).
- Rotate tokens immediately if exposed.

## License

Add a license if you intend to open-source this project.
