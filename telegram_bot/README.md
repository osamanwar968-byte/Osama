# AI Telegram Bot

A small Python Telegram bot that sends text messages to Gemini and returns Arabic
answers through `pyTelegramBotAPI`. The `/image` command fetches generated images
from Pollinations AI and sends them back to Telegram.

## Secure setup

Add these as Replit Secrets. Do not put them in source files:

- `TELEGRAM_BOT_TOKEN` — create a bot with [@BotFather](https://t.me/BotFather)
- `GEMINI_API_KEY` — a Gemini API key from Google AI Studio

Optional environment variables:

- `GEMINI_MODEL` — defaults to `gemini-2.5-flash`
- `BOT_SYSTEM_PROMPT` — customize the assistant’s behavior; the default is Arabic
- `LOG_LEVEL` — defaults to `INFO`

The bot workflow runs with:

```bash
python3 -m telegram_bot
```

## Commands

- `/start` begins the conversation
- `/help` shows the available commands
- `/reset` clears the current chat’s short-term memory
- `/image <prompt>` generates an image with Pollinations AI from a text prompt

The bot’s default replies, command messages, and error messages are in Arabic.

The bot keeps the last six user/assistant turns per chat in memory. Restarting
the workflow clears that memory; no message history is written to disk.

## Local run

```bash
TELEGRAM_BOT_TOKEN=... GEMINI_API_KEY=... python3 -m telegram_bot
```