from openai import AsyncOpenAI

from app.config.settings import Settings
from app.llm.base import LLMProvider, LLMResponse


class OpenAIProvider(LLMProvider):

    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY is not configured."
            )

        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key
        )

        self.model = settings.openai_model

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
    ) -> LLMResponse:

        response = await self.client.responses.create(
            model=self.model,
            instructions=system_prompt,
            input=user_message,
        )

        return LLMResponse(
            content=response.output_text,
            model=self.model,
        )
