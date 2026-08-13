import json
from typing import Any

from app.llm.base import LLMProvider
from app.logging.logger import logger
from app.memory.repository import MemoryRepository
from app.security.permissions import (
    PermissionDecision,
    PermissionEngine,
    PermissionRequest,
)
from app.tools.registry import ToolRegistry

SYSTEM_PROMPT = """
You are JARVIS, a professional personal AI assistant running on macOS.

You have access to explicit tools that allow you to inspect and interact
with the user's computer.

IMPORTANT RULES:

1. Use tools whenever the user's request requires information or actions
   that can be obtained through an available tool.

2. Never fabricate tool results.

3. Never claim an action succeeded unless the tool returned success.

4. Treat tool results as the source of truth.

5. Never invent filesystem paths, usernames, tool results, or system facts.

6. You may use multiple tools sequentially when necessary.

7. If a tool fails, report the actual failure honestly.

8. Never bypass or override the permission system.

9. The security layer, not the language model, makes permission decisions.

10. Keep responses concise and useful.

MEMORY RULES:

11. You have persistent memory stored by JARVIS.

12. When the user explicitly asks you to remember, save, or keep a
    personal preference or fact, store it using the memory system.

13. When answering a question about something the user previously asked
    JARVIS to remember, use the persistent memory context provided to you.

14. Never claim that something was remembered unless it was actually
    stored successfully.

15. If persistent memory does not contain the requested information,
    say that you do not have that information.

TOOL SELECTION RULES:

16. Use the most specific available tool for the user's request.

17. If the user asks to read a specific local file and the read_file tool
    is available, use read_file directly.

18. Do not use terminal commands such as cat, find, grep, mdfind, or similar
    commands as a substitute for read_file when read_file is available.

19. If the user asks to list the contents of a directory and the
    list_directory tool is available, use list_directory directly.

20. If the user asks for information about the Mac itself and the
    get_system_info tool is available, use get_system_info directly.

21. Use the terminal tool when the user explicitly asks to execute a
    terminal command, or when no more specific tool is available.

22. Do not use a more powerful tool when a narrower tool can safely
    accomplish the same task.

23. For multi-step requests, complete each required step using the
    appropriate tool before producing the final answer.
"""


class AgentOrchestrator:
    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        permissions: PermissionEngine,
        memory: MemoryRepository,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.permissions = permissions
        self.memory = memory

    async def run(
        self,
        user_message: str,
    ) -> str:
        request_id = logger.new_request_id()

        self.memory.save_conversation(
            request_id,
            "user",
            user_message,
        )

        previous_conversations = self.memory.get_conversations(
            request_id,
        )

        memory_context = self._build_memory_context()

        conversation_context = self._build_conversation_context(
            previous_conversations,
        )

        user_context = "\n\n".join(
            part
            for part in (
                memory_context,
                conversation_context,
            )
            if part
        )

        tool_schemas = self.tools.openai_schemas()

        response = await self.llm.generate(
            system_prompt=SYSTEM_PROMPT,
            user_message=user_context,
            tools=tool_schemas,
        )

        max_iterations = 10

        for _ in range(max_iterations):
            if not response.tool_calls:
                final_response = response.content

                self._process_memory_request(
                    user_message,
                    final_response,
                )

                self.memory.save_conversation(
                    request_id,
                    "assistant",
                    final_response,
                )

                return final_response

            results: list[tuple[str, str]] = []

            for tool_call in response.tool_calls:
                result = await self._handle_tool_call(
                    tool_call,
                    request_id,
                )

                results.append(
                    (
                        tool_call.call_id,
                        result,
                    )
                )

            response = await self.llm.continue_with_tool_results(
                previous_response=response,
                results=results,
                tools=tool_schemas,
            )

        final_response = (
            "JARVIS stopped because the maximum "
            "agent iteration limit was reached."
        )

        self.memory.save_conversation(
            request_id,
            "assistant",
            final_response,
        )

        return final_response

    def _build_memory_context(self) -> str:
        preferences = self._get_preferences()

        if not preferences:
            return ""

        lines = [
            "Persistent user memory:",
            "",
        ]

        for key, value in preferences.items():
            lines.append(
                f"- {key}: {value}"
            )

        return "\n".join(lines)

    def _get_preferences(self) -> dict[str, str]:
        preferences: dict[str, str] = {}

        known_keys = (
            "favorite_project",
            "favorite_language",
            "preferred_name",
            "preferred_editor",
            "communication_style",
        )

        for key in known_keys:
            value = self.memory.get_preference(key)

            if value is not None:
                preferences[key] = value

        return preferences

    def _process_memory_request(
        self,
        user_message: str,
        assistant_response: str,
    ) -> None:
        message = user_message.strip().lower()

        if not self._is_memory_request(message):
            return

        preference = self._extract_preference(user_message)

        if preference is None:
            return

        key, value = preference

        existing = self.memory.get_preference(key)

        if existing is None:
            self.memory.save_preference(
                key,
                value,
            )
        else:
            self.memory.update_preference(
                key,
                value,
            )

    @staticmethod
    def _is_memory_request(message: str) -> bool:
        memory_phrases = (
            "remember that",
            "remember this",
            "remember my",
            "don't forget that",
            "do not forget that",
            "save this",
            "keep this in mind",
        )

        return any(
            phrase in message
            for phrase in memory_phrases
        )

    @staticmethod
    def _extract_preference(
        message: str,
    ) -> tuple[str, str] | None:
        normalized = message.strip()

        lower = normalized.lower()

        prefix = "remember that "

        if lower.startswith(prefix):
            statement = normalized[len(prefix):].strip()
        else:
            prefix = "remember my "

            if not lower.startswith(prefix):
                return None

            statement = normalized[len(prefix):].strip()

        statement = statement.rstrip(".!?").strip()

        if not statement:
            return None

        lower_statement = statement.lower()

        if lower_statement.startswith("favorite project is "):
            value = statement[len("favorite project is "):].strip()

            if value:
                return "favorite_project", value

        if lower_statement.startswith("favorite project:"):
            value = statement.split(":", 1)[1].strip()

            if value:
                return "favorite_project", value

        if lower_statement.startswith("favorite language is "):
            value = statement[len("favorite language is "):].strip()

            if value:
                return "favorite_language", value

        if lower_statement.startswith("preferred editor is "):
            value = statement[len("preferred editor is "):].strip()

            if value:
                return "preferred_editor", value

        if lower_statement.startswith("preferred name is "):
            value = statement[len("preferred name is "):].strip()

            if value:
                return "preferred_name", value

        return None

    @staticmethod
    def _build_conversation_context(
        conversations: list[dict[str, object]],
    ) -> str:
        if not conversations:
            return ""

        lines = [
            "Current conversation context:",
            "",
        ]

        for conversation in conversations[:-1]:
            role = str(conversation["role"])
            content = str(conversation["content"])

            lines.append(
                f"{role.upper()}: {content}"
            )

        lines.extend(
            [
                "",
                "Current user message:",
                str(conversations[-1]["content"]),
            ]
        )

        return "\n".join(lines)

    async def _handle_tool_call(
        self,
        tool_call: Any,
        request_id: str,
    ) -> str:
        tool = self.tools.get(tool_call.name)

        if tool is None:
            return f"Unknown tool: {tool_call.name}"

        try:
            arguments = json.loads(tool_call.arguments)
        except json.JSONDecodeError as exc:
            return f"Invalid tool arguments: {exc}"

        started = logger.tool_started(
            request_id,
            tool.name,
            arguments,
        )

        permission_level = tool.get_permission(arguments)

        if permission_level.value == "safe":
            decision = PermissionDecision.ALLOW
        elif permission_level.value == "confirm":
            decision = PermissionDecision.CONFIRM
        else:
            decision = PermissionDecision.DENY

        if decision == PermissionDecision.DENY:
            logger.tool_finished(
                request_id,
                tool.name,
                started,
                False,
                "Action blocked by the JARVIS security policy.",
            )

            return "Action blocked by the JARVIS security policy."

        if decision == PermissionDecision.CONFIRM:
            description = self._describe_tool_action(
                tool.name,
                arguments,
            )

            approved = self.permissions.request_confirmation(
                PermissionRequest(
                    tool_name=tool.name,
                    description=description,
                    risk_level=permission_level.value,
                )
            )

            if not approved:
                logger.tool_finished(
                    request_id,
                    tool.name,
                    started,
                    False,
                    "The user denied the requested action.",
                )

                return "The user denied the requested action."

        try:
            result = await tool.execute(arguments)
        except Exception as exc:  # noqa: BLE001
            logger.tool_finished(
                request_id,
                tool.name,
                started,
                False,
                str(exc),
            )

            return f"Tool execution failed: {exc}"

        if result.success:
            logger.tool_finished(
                request_id,
                tool.name,
                started,
                True,
            )

            return result.output

        error = result.error or "Unknown error"

        logger.tool_finished(
            request_id,
            tool.name,
            started,
            False,
            error,
        )

        return f"Tool execution failed: {error}"

    @staticmethod
    def _describe_tool_action(
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        if tool_name == "terminal":
            command = arguments.get(
                "command",
                "",
            )

            working_directory = arguments.get(
                "working_directory",
            )

            description = (
                "Execute terminal command:\n"
                f"  {command}"
            )

            if working_directory:
                description += (
                    "\nWorking directory:\n"
                    f"  {working_directory}"
                )

            return description

        return (
            f"Execute tool '{tool_name}' "
            f"with arguments:\n{arguments}"
        )