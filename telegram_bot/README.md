# AI Telegram Bot

A small Python Telegram bot that sends text messages to Gemini and returns the
answer in Telegram through `pyTelegramBotAPI`. It uses long polling, so it works
without a public webhook URL and is a good first version for a Replit deployment.

## Secure setup

Add these as Replit Secrets. Do not put them in source files:

- `TELEGRAM_BOT_TOKEN` — create a bot with [@BotFather](https://t.me/BotFather)
- `GEMINI_API_KEY` — a Gemini API key from Google AI Studio

Optional environment variables:

- `GEMINI_MODEL` — defaults to `gemini-2.5-flash`
- `GEMINI_IMAGE_MODEL` — defaults to `gemini-2.5-flash-image`
- `BOT_SYSTEM_PROMPT` — customize the assistant’s behavior
- `LOG_LEVEL` — defaults to `INFO`

The bot workflow runs with:

```bash
python3 -m telegram_bot
```

## Commands

- `/start` begins the conversation
- `/help` shows the available commands
- `/reset` clears the current chat’s short-term memory
- `/image <prompt>` generates an image from a text prompt

The bot keeps the last six user/assistant turns per chat in memory. Restarting
the workflow clears that memory; no message history is written to disk.

## Local run

```bash
TELEGRAM_BOT_TOKEN=... GEMINI_API_KEY=... python3 -m telegram_bot
```