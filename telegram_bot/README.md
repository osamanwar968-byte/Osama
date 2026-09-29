# AI Telegram Bot

A small Python Telegram bot that sends text messages to OpenAI and returns the
answer in Telegram. It uses long polling, so it works without a public webhook
URL and is a good first version for a Replit deployment.

## Secure setup

Add these as Replit Secrets. Do not put them in source files:

- `TELEGRAM_BOT_TOKEN` — create a bot with [@BotFather](https://t.me/BotFather)
- `OPENAI_API_KEY` — an OpenAI API key with access to the configured model

Optional environment variables:

- `OPENAI_MODEL` — defaults to `gpt-4o-mini`
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

The bot keeps the last six user/assistant turns per chat in memory. Restarting
the workflow clears that memory; no message history is written to disk.

## Local run

```bash
TELEGRAM_BOT_TOKEN=... OPENAI_API_KEY=... python3 -m telegram_bot
```