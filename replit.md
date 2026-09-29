# AI Telegram Bot

A Python Telegram bot that forwards text messages to Gemini and returns helpful replies with short-term per-chat memory.

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000)
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required env: `DATABASE_URL` — Postgres connection string
- `python3 -m telegram_bot` — run the Telegram bot directly
- Required secrets: `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- API: Express 5
- DB: PostgreSQL + Drizzle ORM
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Build: esbuild (CJS bundle)
- Bot: Python 3.11+, `google-generativeai`, `pyTelegramBotAPI`

## Where things live

- `telegram_bot/main.py` — polling loop, Telegram commands, bounded memory, and AI calls
- `telegram_bot/README.md` — secret setup and usage guide
- `pyproject.toml` — Python project metadata

## Architecture decisions

- The bot uses long polling instead of webhooks so it can run without a public callback URL.
- The first version uses Python’s standard library for HTTP calls, keeping deployment lightweight.
- Conversation history is deliberately in-memory and bounded; no user messages are persisted.
- Gemini and Telegram credentials are read only from environment secrets.

## Product

- Users can chat with an AI assistant from Telegram.
- `/start`, `/help`, and `/reset` provide a simple command surface.
- Long replies are split into Telegram-safe message sizes.

## User preferences

No additional preferences recorded.

## Gotchas

- Add both secrets before starting the bot workflow; startup exits clearly if either is missing.
- Polling memory is lost when the workflow restarts.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
