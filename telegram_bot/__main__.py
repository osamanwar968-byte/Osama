"""Allow the bot to run with ``python3 -m telegram_bot``."""

from .main import run


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        # Keep startup failures visible in the workflow console while leaving
        # the detailed handling in main.py for the running poll loop.
        from .main import ConfigurationError, logger

        if isinstance(exc, ConfigurationError):
            logger.error("%s", exc)
            raise SystemExit(1) from exc
        raise