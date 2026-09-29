"""AI Telegram bot powered by Gemini and pyTelegramBotAPI."""

from __future__ import annotations

import io
import logging
import os
import signal
import sys
from dataclasses import dataclass, field
from typing import Any
from urllib import error, parse, request

import google.generativeai as genai
import telebot


MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
POLLINATIONS_IMAGE_URL = "https://image.pollinations.ai/prompt/"
MAX_HISTORY_MESSAGES = 12
MAX_TELEGRAM_MESSAGE_LENGTH = 4096
SYSTEM_PROMPT = os.getenv(
    "BOT_SYSTEM_PROMPT",
    (
        "أنت مساعد ذكاء اصطناعي مفيد داخل تيليجرام. "
        "أجب باللغة العربية فقط وبأسلوب واضح ومختصر يناسب الهاتف. "
        "لا تستخدم أي لغة أخرى إلا إذا طلب المستخدم ذلك صراحة. "
        "إذا لم تكن متأكدًا، فاذكر ذلك بدلًا من اختلاق المعلومات."
    ),
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("telegram_bot")


class ConfigurationError(RuntimeError):
    """Raised when a required secret is missing."""


class GeminiQuotaError(RuntimeError):
    """Raised when Gemini rejects a request because its quota is exhausted."""


def is_gemini_quota_error(exc: Exception) -> bool:
    details = str(exc).lower()
    return "resource_exhausted" in details or "quota" in details


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(
            f"الإعداد {name} مفقود. أضفه كسرّ في Replit قبل تشغيل البوت."
        )
    if name == "TELEGRAM_BOT_TOKEN" and any(character.isspace() for character in value):
        raise ConfigurationError(
            "يحتوي TELEGRAM_BOT_TOKEN على مسافات. "
            "أدخل الرمز كما أرسله BotFather تمامًا."
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
        try:
            response = self.model.generate_content(
                history,
                generation_config={"max_output_tokens": 700},
            )
        except Exception as exc:
            if is_gemini_quota_error(exc):
                raise GeminiQuotaError(
                    "تم بلوغ حد استخدام Gemini الحالي."
                ) from exc
            raise
        answer = getattr(response, "text", "")
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("أعاد Gemini ردًا فارغًا.")
        return answer.strip()


def fetch_pollinations_image(prompt: str) -> tuple[bytes, str]:
    """Fetch a generated image from Pollinations AI."""
    url = f"{POLLINATIONS_IMAGE_URL}{parse.quote(prompt, safe='')}"
    image_request = request.Request(
        url,
        headers={"User-Agent": "ai-telegram-bot/1.0"},
        method="GET",
    )
    try:
        with request.urlopen(image_request, timeout=90) as response:
            image_data = response.read()
            mime_type = response.headers.get_content_type()
    except error.HTTPError as exc:
        raise RuntimeError(f"رفض Pollinations الطلب برمز HTTP {exc.code}.") from exc
    except error.URLError as exc:
        raise RuntimeError("تعذر الوصول إلى خدمة Pollinations.") from exc
    except TimeoutError as exc:
        raise RuntimeError("انتهت مهلة توليد الصورة.") from exc

    if not mime_type.startswith("image/") or not image_data:
        raise RuntimeError("لم تُرجع Pollinations صورة صالحة.")
    return image_data, mime_type


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
    ) -> None:
        self.bot = telebot.TeleBot(token, parse_mode=None)
        self.assistant = assistant
        self.store = ConversationStore()
        self.register_handlers()

    def register_handlers(self) -> None:
        @self.bot.message_handler(commands=["start"])
        def start(message: telebot.types.Message) -> None:
            self.send(
                message.chat.id,
                (
                    "مرحبًا، أنا مساعدك الذكي.\n\n"
                    "أرسل لي رسالة وسأساعدك في التفكير فيها. "
                    "استخدم /reset لمسح ذاكرة هذه المحادثة المؤقتة."
                ),
            )

        @self.bot.message_handler(commands=["help"])
        def help_command(message: telebot.types.Message) -> None:
            self.send(
                message.chat.id,
                (
                    "الأوامر المتاحة:\n"
                    "/start — بدء المحادثة\n"
                    "/reset — مسح ذاكرة المحادثة المؤقتة\n"
                    "/image <الوصف> — إنشاء صورة\n"
                    "/help — عرض هذه المساعدة"
                ),
            )

        @self.bot.message_handler(commands=["image"])
        def image_command(message: telebot.types.Message) -> None:
            parts = (message.text or "").split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                self.send(
                    message.chat.id,
                    "الاستخدام: /image <وصف الصورة التي تريد إنشاءها>",
                )
                return

            prompt = parts[1].strip()
            self.bot.send_chat_action(message.chat.id, "upload_photo")
            try:
                image_data, mime_type = fetch_pollinations_image(prompt)
            except Exception:
                logger.exception(
                    "فشل توليد الصورة للمحادثة %s",
                    message.chat.id,
                )
                self.send(
                    message.chat.id,
                    (
                        "تعذر إنشاء الصورة الآن. "
                        "حاول استخدام وصف مختلف بعد قليل."
                    ),
                )
                return

            image = io.BytesIO(image_data)
            image.name = "generated.png" if mime_type == "image/png" else "generated.jpg"
            self.bot.send_photo(
                message.chat.id,
                image,
                caption=f"تم إنشاء الصورة من: {prompt[:900]}",
            )

        @self.bot.message_handler(commands=["reset"])
        def reset(message: telebot.types.Message) -> None:
            self.store.reset(message.chat.id)
            self.send(message.chat.id, "تم مسح ذاكرة المحادثة المؤقتة.")

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
            except GeminiQuotaError:
                logger.warning("تم بلوغ حصة Gemini للمحادثة %s", message.chat.id)
                self.store.conversations[message.chat.id].pop()
                self.send(
                    message.chat.id,
                    (
                        "تم الوصول إلى حد استخدام Gemini المجاني حاليًا. "
                        "حاول مرة أخرى لاحقًا."
                    ),
                )
                return
            except Exception:
                logger.exception("فشل رد Gemini للمحادثة %s", message.chat.id)
                self.store.conversations[message.chat.id].pop()
                self.send(
                    message.chat.id,
                    (
                        "حدثت مشكلة مؤقتة أثناء التفكير. "
                        "حاول مرة أخرى بعد قليل."
                    ),
                )
                return
            self.store.add(message.chat.id, "assistant", answer)
            self.send(message.chat.id, answer)

        @self.bot.message_handler(
            content_types=["audio", "document", "photo", "sticker", "video", "voice"]
        )
        def unsupported_message(message: telebot.types.Message) -> None:
            self.send(message.chat.id, "أستطيع الرد على الرسائل النصية والصور المنشأة حاليًا.")

    def send(self, chat_id: int, text: str) -> None:
        for chunk in split_message(text):
            self.bot.send_message(chat_id, chunk)

    def run(self) -> None:
        bot_info = self.bot.get_me()
        logger.info(
            "بدأ بوت تيليجرام الذكي باسم @%s باستخدام %s",
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
    )

    def stop_handler(signum: int, _frame: Any) -> None:
        logger.info("تم استلام الإشارة %s؛ جارٍ إيقاف البوت.", signum)
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