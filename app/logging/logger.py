import json
import logging
import time
import uuid
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "jarvis.log"


class StructuredLogger:
    def __init__(self, name: str = "jarvis"):
        self.logger = logging.getLogger(name)

        if not self.logger.handlers:
            formatter = logging.Formatter("%(message)s")

            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            self.logger.addHandler(stream_handler)

            LOG_DIR.mkdir(parents=True, exist_ok=True)

            file_handler = RotatingFileHandler(
                LOG_FILE,
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

    @staticmethod
    def new_request_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def sanitize_arguments(
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        sensitive_keys = {
            "api_key",
            "apikey",
            "authorization",
            "token",
            "password",
            "secret",
            "access_token",
            "refresh_token",
        }

        def sanitize(
            value: Any,
            key: str | None = None,
        ) -> Any:
            if key and key.lower() in sensitive_keys:
                return "[REDACTED]"

            if isinstance(value, dict):
                return {str(k): sanitize(v, str(k)) for k, v in value.items()}

            if isinstance(value, list):
                return [sanitize(item) for item in value]

            if isinstance(value, tuple):
                return [sanitize(item) for item in value]

            return value

        return sanitize(arguments)

    def tool_started(
        self,
        request_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> float:
        started = time.perf_counter()

        self._write(
            event="tool_started",
            request_id=request_id,
            tool=tool_name,
            arguments=self.sanitize_arguments(arguments),
        )

        return started

    def tool_finished(
        self,
        request_id: str,
        tool_name: str,
        started: float,
        success: bool,
        error: str | None = None,
    ) -> None:
        duration_ms = round(
            (time.perf_counter() - started) * 1000,
            2,
        )

        data: dict[str, Any] = {
            "event": "tool_finished",
            "request_id": request_id,
            "tool": tool_name,
            "status": "success" if success else "failure",
            "duration_ms": duration_ms,
        }

        if error:
            data["error"] = error

        self._write(**data)

    def _write(self, **data: Any) -> None:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            **data,
        }

        self.logger.info(
            json.dumps(
                payload,
                ensure_ascii=False,
                default=str,
            )
        )


logger = StructuredLogger()
