"""Flask web interface for the Arabic AI assistant."""

from __future__ import annotations

import logging
import os
import threading
import uuid
from io import BytesIO
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file

from .main import (
    GeminiAssistant,
    GeminiQuotaError,
    TelegramBot,
    fetch_pollinations_image,
    required_env,
)


logger = logging.getLogger("telegram_web")
app = Flask(__name__, template_folder="templates", static_folder="static")

assistant: GeminiAssistant | None = None
telegram_bot: TelegramBot | None = None
assistant_lock = threading.Lock()
web_conversations: dict[str, list[dict[str, str]]] = {}


def gemini_history(history: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "role": "model" if message["role"] == "assistant" else "user",
            "parts": [{"text": message["content"]}],
        }
        for message in history
    ]


def get_services() -> tuple[GeminiAssistant, TelegramBot]:
    global assistant, telegram_bot
    if assistant is None or telegram_bot is None:
        token = required_env("TELEGRAM_BOT_TOKEN")
        gemini_key = required_env("GEMINI_API_KEY")
        assistant = GeminiAssistant(gemini_key)
        telegram_bot = TelegramBot(token, assistant)
    return assistant, telegram_bot


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/health")
def health() -> tuple[Any, int]:
    return jsonify({"status": "يعمل", "message": "الخدمة تعمل بشكل طبيعي."}), 200


@app.post("/api/chat")
def chat() -> tuple[Any, int]:
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message", "")).strip()
    if not message:
        return jsonify({"error": "اكتب رسالة أولًا."}), 400

    session_id = str(payload.get("session_id") or uuid.uuid4().hex)
    current_assistant, _ = get_services()
    history = web_conversations.setdefault(session_id, [])
    history.append({"role": "user", "content": message})

    try:
        with assistant_lock:
            reply = current_assistant.reply(gemini_history(history))
    except GeminiQuotaError:
        logger.warning("تم بلوغ حصة Gemini من واجهة الويب")
        history.pop()
        return (
            jsonify(
                {
                    "error": (
                        "تم الوصول إلى حد استخدام Gemini المجاني حاليًا. "
                        "حاول مرة أخرى لاحقًا."
                    )
                }
            ),
            429,
        )
    except Exception:
        logger.exception("فشل رد Gemini من واجهة الويب")
        history.pop()
        return (
            jsonify(
                {
                    "error": (
                        "حدثت مشكلة مؤقتة أثناء معالجة رسالتك. "
                        "حاول مرة أخرى بعد قليل."
                    )
                }
            ),
            502,
        )

    history.append({"role": "assistant", "content": reply})
    return jsonify({"session_id": session_id, "reply": reply}), 200


@app.post("/api/image")
def image() -> tuple[Any, int] | Any:
    payload = request.get_json(silent=True) or {}
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        return jsonify({"error": "اكتب وصفًا للصورة أولًا."}), 400

    try:
        image_data, mime_type = fetch_pollinations_image(prompt)
    except Exception:
        logger.exception("فشل إنشاء صورة من واجهة الويب")
        return (
            jsonify(
                {
                    "error": (
                        "تعذر إنشاء الصورة الآن. "
                        "حاول استخدام وصف مختلف بعد قليل."
                    )
                }
            ),
            502,
        )

    extension = "png" if mime_type == "image/png" else "jpg"
    return send_file(
        BytesIO(image_data),
        mimetype=mime_type,
        as_attachment=False,
        download_name=f"pollinations-image.{extension}",
    )


def run() -> None:
    current_assistant, current_telegram_bot = get_services()
    del current_assistant
    telegram_thread = threading.Thread(
        target=current_telegram_bot.run,
        name="telegram-polling",
        daemon=True,
    )
    telegram_thread.start()

    port = int(os.getenv("PORT", "8000"))
    logger.info("بدأت واجهة الويب العربية على المنفذ %s", port)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    run()