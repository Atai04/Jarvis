import json
import logging
import time
import uuid
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from app.llm.base import LLMResponse, TokenUsage
from app.voice.privacy import private_audio_request

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

    def model_usage(self, request_id: str, usage: TokenUsage | None) -> None:
        """Log only allowlisted counters, never prompts or raw API responses."""
        self._write(
            event="model_usage",
            request_id=request_id,
            input_tokens=usage.input_tokens if usage is not None else None,
            output_tokens=usage.output_tokens if usage is not None else None,
            total_tokens=usage.total_tokens if usage is not None else None,
        )

    def model_context(
        self,
        request_id: str,
        *,
        memory_chars: int,
        conversation_chars: int,
        user_message_chars: int,
    ) -> None:
        self._write(
            event="model_context",
            request_id=request_id,
            memory_chars=memory_chars,
            conversation_chars=conversation_chars,
            user_message_chars=user_message_chars,
        )

    def model_diagnostics(self, request_id: str, response: LLMResponse) -> None:
        """Explicit allowlist: never serialize raw responses, actions or queries."""
        metrics = response.request_metrics
        self._write(
            event="model_diagnostics",
            request_id=request_id,
            web_search_occurred=response.web_search_call_count > 0,
            web_search_call_count=response.web_search_call_count,
            web_search_completed_count=response.web_search_completed_count,
            web_search_offered=metrics.web_search_offered if metrics else None,
            continuation=metrics.continuation if metrics else None,
            instructions_chars=metrics.instructions_chars if metrics else None,
            custom_tool_schema_json_chars=metrics.custom_tool_schema_json_chars
            if metrics
            else None,
            custom_tool_count=metrics.custom_tool_count if metrics else None,
            input_json_chars=metrics.input_json_chars if metrics else None,
        )

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

    def speech_playback(
        self, *, selected_provider: str, playback_provider: str | None,
        fallback_occurred: bool, outcome: str,
    ) -> None:
        self._write(
            event="speech_playback", selected_provider=selected_provider,
            playback_provider=playback_provider, fallback_occurred=fallback_occurred,
            outcome=outcome,
        )

    def _write(self, **data: Any) -> None:
        if private_audio_request.get():
            # Voice turns can put the transcript in tool arguments or errors.
            # Keep operational counters/status, not free-form content.
            data = {
                key: value for key, value in data.items()
                if key not in {"arguments", "error"}
            }
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
