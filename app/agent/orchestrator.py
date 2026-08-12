from app.llm.base import LLMProvider


SYSTEM_PROMPT = """
You are JARVIS, a professional personal AI assistant.

Your job is to help the user accomplish tasks accurately,
safely, and efficiently.

Important rules:

- Never fabricate information.
- Never claim an action succeeded unless it actually succeeded.
- Be concise but useful.
- Ask for clarification only when necessary.
- Tools will be introduced separately.
- Do not pretend that tools exist when they are not available.

You are currently running in Phase 1 of the JARVIS system.
"""


class AgentOrchestrator:

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    async def run(self, user_message: str) -> str:
        response = await self.llm.generate(
            system_prompt=SYSTEM_PROMPT,
            user_message=user_message,
        )

        return response.content
