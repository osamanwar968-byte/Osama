"""A small, dependency-free AI Telegram bot.

The bot uses Telegram long polling and OpenAI's chat completions endpoint
directly over HTTPS. This keeps the first version easy to run on Replit and
avoids coupling the app to a framework that is not needed for this use case.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import Any
from urllib import error, request


TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
OPENAI_API = "https://api.openai.com/v1/chat/completions"
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_HISTORY_MESSAGES = 12
MAX_TELEGRAM_MESSAGE_LENGTH = 4096
POLL_TIMEOUT_SECONDS = 30
REQUEST_TIMEOUT_SECONDS = 45

SYSTEM_PROMPT = os.getenv(
    "BOT_SYSTEM_PROMPT",
    (
        "You are a helpful AI assistant inside Telegram. "
        "Answer clearly and concisely. Use plain text that reads well on a phone. "
        "If you are unsure, say so instead of inventing facts."
    ),
)


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("telegram_bot")


class ConfigurationError(RuntimeError):
    """Raised when required environment variables are missing."""


class ApiError(RuntimeError):
    """Raised when a Telegram or OpenAI request fails."""


@dataclass
class ConversationStore:
    """Bounded in-memory conversation history keyed by Telegram chat ID."""

    conversations: dict[int, list[dict[str, str]]] = field(default_factory=dict)

    def messages_for(self, chat_id: int) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            *self.conversations.get(chat_id, []),
        ]

    def add(self, chat_id: int, role: str, content: str) -> None:
        history = self.conversations.setdefault(chat_id, [])
        history.append({"role": role, "content": content})
        self.conversations[chat_id] = history[-MAX_HISTORY_MESSAGES:]

    def reset(self, chat_id: int) -> None:
        self.conversations.pop(chat_id, None)


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(
            f"Missing {name}. Add it as a Replit Secret before starting the bot."
        )
    return value


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    http_request = request.Request(
        url,
        data=body,
        headers=request_headers,
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ApiError(f"HTTP {exc.code}: {detail[:500]}") from exc
    except error.URLError as exc:
        raise ApiError(f"Network error: {exc.reason}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiError("The API returned invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ApiError("The API returned an unexpected response.")
    return parsed


def telegram_call(
    token: str,
    method: str,
    payload: dict[str, Any],
    *,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> Any:
    url = TELEGRAM_API.format(token=token, method=method)
    response = post_json(url, payload, timeout=timeout)
    if not response.get("ok"):
        description = response.get("description", "Unknown Telegram error")
        raise ApiError(f"Telegram {method} failed: {description}")
    return response.get("result")


def get_updates(token: str, offset: int | None) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {
        "timeout": POLL_TIMEOUT_SECONDS,
        "allowed_updates": ["message"],
    }
    if offset is not None:
        payload["offset"] = offset
    return telegram_call(
        token,
        "getUpdates",
        payload,
        timeout=POLL_TIMEOUT_SECONDS + 10,
    )


def send_message(token: str, chat_id: int, text: str) -> None:
    for chunk in split_message(text):
        telegram_call(token, "sendMessage", {"chat_id": chat_id, "text": chunk})


def split_message(text: str) -> list[str]:
    """Split a response without exceeding Telegram's 4096-character limit."""
    clean_text = text.strip() or "I wasn't able to generate a response."
    chunks: list[str] = []
    remaining = clean_text
    while len(remaining) > MAX_TELEGRAM_MESSAGE_LENGTH:
        split_at = remaining.rfind(
            "\n", 0, MAX_TELEGRAM_MESSAGE_LENGTH + 1
        )
        if split_at < MAX_TELEGRAM_MESSAGE_LENGTH // 2:
            split_at = remaining.rfind(
                " ", 0, MAX_TELEGRAM_MESSAGE_LENGTH + 1
            )
        if split_at < MAX_TELEGRAM_MESSAGE_LENGTH // 2:
            split_at = MAX_TELEGRAM_MESSAGE_LENGTH
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def ask_openai(api_key: str, messages: list[dict[str, str]]) -> str:
    response = post_json(
        OPENAI_API,
        {
            "model": MODEL,
            "messages": messages,
            "max_tokens": 700,
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ApiError("OpenAI returned no choices.")
    message = choices[0].get("message", {})
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ApiError("OpenAI returned an empty response.")
    return content.strip()


def command_response(command: str) -> str | None:
    normalized = command.split("@", 1)[0].lower()
    if normalized == "/start":
        return (
            "Hi. I’m your AI assistant.\n\n"
            "Send me a message and I’ll help you think it through. "
            "Use /reset to clear this chat’s short-term memory."
        )
    if normalized == "/help":
        return (
            "Available commands:\n"
            "/start — start chatting\n"
            "/reset — clear this chat’s short-term memory\n"
            "/help — show this help"
        )
    if normalized == "/reset":
        return ""
    return None


def handle_message(
    token: str,
    openai_key: str,
    store: ConversationStore,
    message: dict[str, Any],
) -> None:
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    if not isinstance(chat_id, int):
        return

    text = message.get("text")
    if not isinstance(text, str) or not text.strip():
        send_message(token, chat_id, "I can respond to text messages for now.")
        return

    if text.startswith("/"):
        response = command_response(text.split()[0])
        if response is not None:
            if text.split()[0].split("@", 1)[0].lower() == "/reset":
                store.reset(chat_id)
                send_message(token, chat_id, "Done. I cleared our conversation memory.")
            else:
                send_message(token, chat_id, response)
            return

    telegram_call(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})
    store.add(chat_id, "user", text.strip())
    try:
        answer = ask_openai(openai_key, store.messages_for(chat_id))
    except ApiError:
        logger.exception("AI response failed for chat %s", chat_id)
        store.conversations[chat_id].pop()
        send_message(
            token,
            chat_id,
            "I hit a temporary problem while thinking. Please try again in a moment.",
        )
        return
    store.add(chat_id, "assistant", answer)
    send_message(token, chat_id, answer)


def run() -> None:
    token = required_env("TELEGRAM_BOT_TOKEN")
    openai_key = required_env("OPENAI_API_KEY")
    store = ConversationStore()
    stopping = False

    def stop_handler(signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True
        logger.info("Received signal %s; stopping after the current poll.", signum)

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    bot_info = telegram_call(token, "getMe", {})
    bot_username = bot_info.get("username", "unknown") if isinstance(bot_info, dict) else "unknown"
    logger.info("AI Telegram bot started as @%s using model %s", bot_username, MODEL)

    offset: int | None = None
    while not stopping:
        try:
            updates = get_updates(token, offset)
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = update_id + 1
                message = update.get("message")
                if isinstance(message, dict):
                    handle_message(token, openai_key, store, message)
        except ApiError:
            logger.exception("Polling failed; retrying in 5 seconds.")
            time.sleep(5)
        except Exception:
            logger.exception("Unexpected bot error; retrying in 5 seconds.")
            time.sleep(5)

    logger.info("AI Telegram bot stopped.")


if __name__ == "__main__":
    try:
        run()
    except ConfigurationError as exc:
        logger.error("%s", exc)
        sys.exit(1)