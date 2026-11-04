import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    call_id: str
    name: str
    arguments: str


@dataclass
class SourceCitation:
    url: str
    title: str
    start_index: int
    end_index: int


@dataclass
class TokenUsage:
    """API-reported counts; None means unavailable, not zero."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class RequestMetrics:
    """Local character counts, never token estimates or request content."""

    instructions_chars: int
    custom_tool_schema_json_chars: int
    input_json_chars: int
    custom_tool_count: int
    web_search_offered: bool
    continuation: bool


@dataclass
class LLMResponse:
    content: str
    model: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_response: Any = None
    citations: list[SourceCitation] = field(default_factory=list)
    system_prompt: str | None = None
    usage: TokenUsage | None = None
    web_search_requests: int = 0
    web_search_call_count: int = 0
    web_search_completed_count: int = 0
    request_metrics: RequestMetrics | None = None

    def display_text(self) -> str:
        """Expose source URLs inline in the CLI without changing raw content."""
        text = self.content
        missing: dict[str, SourceCitation] = {}
        for citation in self.citations:
            # Match a complete URL, not a prefix of a different path/query. Keep
            # existing Markdown links, autolinks and bare URLs exactly as given.
            if not citation.url or re.search(
                re.escape(citation.url) + r'(?=$|[\s<>"\]\)]|[.,;!?](?:\s|$))',
                self.content,
            ):
                continue
            missing.setdefault(citation.url, citation)
        for citation in sorted(
            missing.values(), key=lambda source: source.end_index, reverse=True
        ):
            position = max(0, min(citation.end_index, len(self.content)))
            text = text[:position] + f" ({citation.url})" + text[position:]
        return text


class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        raise NotImplementedError

    @abstractmethod
    async def continue_with_tool_results(
        self,
        previous_response: LLMResponse,
        results: list[tuple[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        raise NotImplementedError
