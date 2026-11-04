import json
from typing import Any

from openai import AsyncOpenAI

from app.config.settings import Settings
from app.llm.base import (
    LLMProvider,
    LLMResponse,
    RequestMetrics,
    SourceCitation,
    TokenUsage,
    ToolCall,
)


class OpenAIProvider(LLMProvider):
    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")

        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model

        self.web_search_enabled = settings.web_search_enabled
        self.web_search_max_requests_per_turn = (
            settings.web_search_max_requests_per_turn
        )

    def enable_web_search(self) -> None:
        self.web_search_enabled = True

    def _build_tools(
        self,
        tools: list[dict[str, Any]] | None,
        *,
        web_search_requests: int = 0,
    ) -> list[dict[str, Any]]:
        # Native search is provider-owned. Normalize aliases and duplicates while
        # leaving custom functions (including one named web_search) untouched.
        search_types = {
            "web_search",
            "web_search_2025_08_26",
            "web_search_preview",
            "web_search_preview_2025_03_11",
        }
        result = []
        search_options: dict[str, Any] | None = None
        for tool in tools or []:
            if tool.get("type") in search_types:
                if search_options is None:
                    search_options = dict(tool)
            else:
                result.append(tool)

        if (
            self.web_search_enabled
            and web_search_requests < self.web_search_max_requests_per_turn
        ):
            result.append(
                {
                    **(search_options or {}),
                    "type": "web_search",
                    "search_context_size": "low",
                }
            )

        return result

    @staticmethod
    def _request_metrics(
        instructions: str | None,
        input_value: Any,
        tools: list[dict[str, Any]],
        *,
        continuation: bool = False,
    ) -> RequestMetrics:
        custom_tools = [tool for tool in tools if tool.get("type") == "function"]
        return RequestMetrics(
            instructions_chars=len(instructions or ""),
            custom_tool_schema_json_chars=len(
                json.dumps(custom_tools, ensure_ascii=False, separators=(",", ":"))
            ),
            input_json_chars=len(
                json.dumps(input_value, ensure_ascii=False, separators=(",", ":"))
            ),
            custom_tool_count=len(custom_tools),
            web_search_offered=any(tool.get("type") == "web_search" for tool in tools),
            continuation=continuation,
        )

    @staticmethod
    def _parse_response(
        response: Any,
        model: str,
        system_prompt: str | None = None,
        web_search_requests: int = 0,
        request_metrics: RequestMetrics | None = None,
    ) -> LLMResponse:
        tool_calls: list[ToolCall] = []
        citations: list[SourceCitation] = []
        text_offset = 0
        search_calls = 0
        completed_search_calls = 0

        for item in response.output:
            if item.type == "web_search_call":
                search_calls += 1
                completed_search_calls += int(
                    getattr(item, "status", None) == "completed"
                )
            elif item.type == "function_call":
                tool_calls.append(
                    ToolCall(
                        call_id=item.call_id,
                        name=item.name,
                        arguments=item.arguments,
                    )
                )

            elif item.type == "message":
                for content in item.content:
                    if content.type != "output_text":
                        continue
                    for annotation in content.annotations:
                        if annotation.type == "url_citation":
                            citations.append(
                                SourceCitation(
                                    url=annotation.url,
                                    title=annotation.title,
                                    start_index=text_offset + annotation.start_index,
                                    end_index=text_offset + annotation.end_index,
                                )
                            )
                    text_offset += len(content.text)

        raw_usage = getattr(response, "usage", None)
        usage = None
        if raw_usage is not None:
            usage = TokenUsage(
                input_tokens=getattr(raw_usage, "input_tokens", None),
                output_tokens=getattr(raw_usage, "output_tokens", None),
                total_tokens=getattr(raw_usage, "total_tokens", None),
            )

        return LLMResponse(
            content=response.output_text or "",
            model=model,
            tool_calls=tool_calls,
            raw_response=response,
            citations=citations,
            system_prompt=system_prompt,
            usage=usage,
            web_search_requests=web_search_requests,
            web_search_call_count=search_calls,
            web_search_completed_count=completed_search_calls,
            request_metrics=request_metrics,
        )

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        # Each generate starts a turn; continuation carries its own counter.
        request_tools = self._build_tools(tools)
        response = await self.client.responses.create(
            model=self.model,
            instructions=system_prompt,
            input=user_message,
            tools=request_tools,
            parallel_tool_calls=False,
        )

        return self._parse_response(
            response,
            self.model,
            system_prompt,
            web_search_requests=int(
                any(t["type"] == "web_search" for t in request_tools)
            ),
            request_metrics=self._request_metrics(
                system_prompt, user_message, request_tools
            ),
        )

    async def continue_with_tool_results(
        self,
        previous_response: LLMResponse,
        results: list[tuple[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        if previous_response.raw_response is None:
            raise RuntimeError("Previous response is missing.")

        input_items = [
            {
                "type": "function_call_output",
                "call_id": call_id,
                "output": result,
            }
            for call_id, result in results
        ]

        request_tools = self._build_tools(
            tools, web_search_requests=previous_response.web_search_requests
        )
        response = await self.client.responses.create(
            model=self.model,
            previous_response_id=previous_response.raw_response.id,
            # Responses does not inherit instructions via previous_response_id.
            instructions=previous_response.system_prompt,
            input=input_items,
            tools=request_tools,
            parallel_tool_calls=False,
        )

        return self._parse_response(
            response,
            self.model,
            previous_response.system_prompt,
            web_search_requests=previous_response.web_search_requests
            + int(any(t["type"] == "web_search" for t in request_tools)),
            request_metrics=self._request_metrics(
                previous_response.system_prompt,
                input_items,
                request_tools,
                continuation=True,
            ),
        )
