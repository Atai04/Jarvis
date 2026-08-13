from typing import Any

from openai import AsyncOpenAI

from app.config.settings import Settings
from app.llm.base import LLMProvider, LLMResponse, ToolCall


class OpenAIProvider(LLMProvider):
    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")

        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

        self.model = settings.openai_model

    @staticmethod
    def _parse_response(
        response: Any,
        model: str,
    ) -> LLMResponse:

        tool_calls: list[ToolCall] = []

        for item in response.output:
            if item.type == "function_call":
                tool_calls.append(
                    ToolCall(
                        call_id=item.call_id,
                        name=item.name,
                        arguments=item.arguments,
                    )
                )

        return LLMResponse(
            content=response.output_text or "",
            model=model,
            tool_calls=tool_calls,
            raw_response=response,
        )

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:

        response = await self.client.responses.create(
            model=self.model,
            instructions=system_prompt,
            input=user_message,
            tools=tools or [],
            parallel_tool_calls=False,
        )

        return self._parse_response(
            response,
            self.model,
        )

    async def continue_with_tool_results(
        self,
        previous_response: LLMResponse,
        results: list[tuple[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:

        if previous_response.raw_response is None:
            raise RuntimeError("Previous response is missing.")

        input_items = []

        for call_id, result in results:
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": result,
                }
            )

        response = await self.client.responses.create(
            model=self.model,
            previous_response_id=previous_response.raw_response.id,
            input=input_items,
            tools=tools or [],
            parallel_tool_calls=False,
        )

        return self._parse_response(
            response,
            self.model,
        )
