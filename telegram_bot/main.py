"""AI Telegram bot powered by Gemini and pyTelegramBotAPI."""

from __future__ import annotations

import base64
import io
import logging
import os
import signal
import sys
from dataclasses import dataclass, field
from typing import Any

import google.generativeai as genai
import telebot


MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
MAX_HISTORY_MESSAGES = 12
MAX_TELEGRAM_MESSAGE_LENGTH = 4096
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
    """Raised when a required secret is missing."""


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(
            f"Missing {name}. Add it as a Replit Secret before starting the bot."
        )
    if name == "TELEGRAM_BOT_TOKEN" and any(character.isspace() for character in value):
        raise ConfigurationError(
            "TELEGRAM_BOT_TOKEN contains whitespace. "
            "Enter the token exactly as provided by BotFather."
        )
    return value


@dataclass
class ConversationStore:
    """Bounded in-memory conversation history keyed by Telegram chat ID."""

    conversations: dict[int, list[dict[str, str]]] = field(default_factory=dict)

    def add(self, chat_id: int, role: str, content: str) -> None:
        history = self.conversations.setdefault(chat_id, [])
        history.append({"role": role, "content": content})
        self.conversations[chat_id] = history[-MAX_HISTORY_MESSAGES:]

    def for_gemini(self, chat_id: int) -> list[dict[str, Any]]:
        return [
            {
                "role": "model" if item["role"] == "assistant" else "user",
                "parts": [{"text": item["content"]}],
            }
            for item in self.conversations.get(chat_id, [])
        ]

    def reset(self, chat_id: int) -> None:
        self.conversations.pop(chat_id, None)


class GeminiAssistant:
    """Small adapter around the requested google-generativeai SDK."""

    def __init__(self, api_key: str) -> None:
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            model_name=MODEL,
            system_instruction=SYSTEM_PROMPT,
        )

    def reply(self, history: list[dict[str, Any]]) -> str:
        response = self.model.generate_content(
            history,
            generation_config={"max_output_tokens": 700},
        )
        answer = getattr(response, "text", "")
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("Gemini returned an empty response.")
        return answer.strip()


class GeminiImageGenerator:
    """Generate an image using Gemini's native image output."""

    def __init__(self, api_key: str) -> None:
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name=IMAGE_MODEL)

    def generate(self, prompt: str) -> tuple[bytes, str]:
        response = self.model.generate_content(prompt)
        for part in response.parts:
            inline_data = getattr(part, "inline_data", None)
            if inline_data is None:
                continue
            data = inline_data.data
            if isinstance(data, str):
                data = base64.b64decode(data)
            if isinstance(data, bytes):
                return data, getattr(inline_data, "mime_type", "image/png")
        raise RuntimeError("Gemini did not return an image.")


def split_message(text: str) -> list[str]:
    """Split a response without exceeding Telegram's message limit."""
    remaining = text.strip() or "I wasn't able to generate a response."
    chunks: list[str] = []
    while len(remaining) > MAX_TELEGRAM_MESSAGE_LENGTH:
        split_at = remaining.rfind("\n", 0, MAX_TELEGRAM_MESSAGE_LENGTH + 1)
        if split_at < MAX_TELEGRAM_MESSAGE_LENGTH // 2:
            split_at = remaining.rfind(" ", 0, MAX_TELEGRAM_MESSAGE_LENGTH + 1)
        if split_at < MAX_TELEGRAM_MESSAGE_LENGTH // 2:
            split_at = MAX_TELEGRAM_MESSAGE_LENGTH
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


class TelegramBot:
    """Telegram handlers and the chat-memory boundary."""

    def __init__(
        self,
        token: str,
        assistant: GeminiAssistant,
        image_generator: GeminiImageGenerator,
    ) -> None:
        self.bot = telebot.TeleBot(token, parse_mode=None)
        self.assistant = assistant
        self.image_generator = image_generator
        self.store = ConversationStore()
        self.register_handlers()

    def register_handlers(self) -> None:
        @self.bot.message_handler(commands=["start"])
        def start(message: telebot.types.Message) -> None:
            self.send(
                message.chat.id,
                (
                    "Hi. I’m your AI assistant.\n\n"
                    "Send me a message and I’ll help you think it through. "
                    "Use /reset to clear this chat’s short-term memory."
                ),
            )

        @self.bot.message_handler(commands=["help"])
        def help_command(message: telebot.types.Message) -> None:
            self.send(
                message.chat.id,
                (
                    "Available commands:\n"
                    "/start — start chatting\n"
                    "/reset — clear this chat’s short-term memory\n"
                    "/image <prompt> — generate an image\n"
                    "/help — show this help"
                ),
            )

        @self.bot.message_handler(commands=["image"])
        def image_command(message: telebot.types.Message) -> None:
            parts = (message.text or "").split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                self.send(
                    message.chat.id,
                    "Usage: /image <what you want to create>",
                )
                return

            prompt = parts[1].strip()
            self.bot.send_chat_action(message.chat.id, "upload_photo")
            try:
                image_data, mime_type = self.image_generator.generate(prompt)
            except Exception:
                logger.exception(
                    "Gemini image generation failed for chat %s",
                    message.chat.id,
                )
                self.send(
                    message.chat.id,
                    (
                        "I couldn't generate that image right now. "
                        "Please try a different prompt."
                    ),
                )
                return

            image = io.BytesIO(image_data)
            image.name = "generated.png" if mime_type == "image/png" else "generated.jpg"
            self.bot.send_photo(
                message.chat.id,
                image,
                caption=f"Generated from: {prompt[:900]}",
            )

        @self.bot.message_handler(commands=["reset"])
        def reset(message: telebot.types.Message) -> None:
            self.store.reset(message.chat.id)
            self.send(message.chat.id, "Done. I cleared our conversation memory.")

        @self.bot.message_handler(content_types=["text"])
        def text_message(message: telebot.types.Message) -> None:
            text = (message.text or "").strip()
            if not text:
                return
            self.bot.send_chat_action(message.chat.id, "typing")
            self.store.add(message.chat.id, "user", text)
            try:
                answer = self.assistant.reply(
                    self.store.for_gemini(message.chat.id)
                )
            except Exception:
                logger.exception("Gemini response failed for chat %s", message.chat.id)
                self.store.conversations[message.chat.id].pop()
                self.send(
                    message.chat.id,
                    (
                        "I hit a temporary problem while thinking. "
                        "Please try again in a moment."
                    ),
                )
                return
            self.store.add(message.chat.id, "assistant", answer)
            self.send(message.chat.id, answer)

        @self.bot.message_handler(
            content_types=["audio", "document", "photo", "sticker", "video", "voice"]
        )
        def unsupported_message(message: telebot.types.Message) -> None:
            self.send(message.chat.id, "I can respond to text messages for now.")

    def send(self, chat_id: int, text: str) -> None:
        for chunk in split_message(text):
            self.bot.send_message(chat_id, chunk)

    def run(self) -> None:
        bot_info = self.bot.get_me()
        logger.info(
            "AI Telegram bot started as @%s using %s",
            getattr(bot_info, "username", "unknown"),
            MODEL,
        )
        self.bot.infinity_polling(
            timeout=30,
            long_polling_timeout=30,
            skip_pending=True,
        )

    def stop(self) -> None:
        self.bot.stop_bot()


def run() -> None:
    token = required_env("TELEGRAM_BOT_TOKEN")
    gemini_key = required_env("GEMINI_API_KEY")
    application = TelegramBot(
        token,
        GeminiAssistant(gemini_key),
        GeminiImageGenerator(gemini_key),
    )

    def stop_handler(signum: int, _frame: Any) -> None:
        logger.info("Received signal %s; stopping the bot.", signum)
        application.stop()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    application.run()


if __name__ == "__main__":
    try:
        run()
    except ConfigurationError as exc:
        logger.error("%s", exc)
        sys.exit(1)