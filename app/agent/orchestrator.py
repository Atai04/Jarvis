import json
from typing import Any

from app.llm.base import LLMProvider
from app.logging.logger import logger
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

TOOL SELECTION RULES:

11. Use the most specific available tool for the user's request.

12. If the user asks to read a specific local file and the read_file tool
    is available, use read_file directly.

13. Do not use terminal commands such as cat, find, grep, mdfind, or similar
    commands as a substitute for read_file when read_file is available.

14. If the user asks to list the contents of a directory and the
    list_directory tool is available, use list_directory directly.

15. If the user asks for information about the Mac itself and the
    get_system_info tool is available, use get_system_info directly.

16. Use the terminal tool when the user explicitly asks to execute a
    terminal command, or when no more specific tool is available.

17. Do not use a more powerful tool when a narrower tool can safely
    accomplish the same task.

18. For multi-step requests, complete each required step using the
    appropriate tool before producing the final answer.
"""


class AgentOrchestrator:
    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        permissions: PermissionEngine,
    ):
        self.llm = llm
        self.tools = tools
        self.permissions = permissions

    async def run(
        self,
        user_message: str,
    ) -> str:
        request_id = logger.new_request_id()

        tool_schemas = self.tools.openai_schemas()

        response = await self.llm.generate(
            system_prompt=SYSTEM_PROMPT,
            user_message=user_message,
            tools=tool_schemas,
        )

        max_iterations = 10

        for _ in range(max_iterations):
            if not response.tool_calls:
                return response.content

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

        return (
            "JARVIS stopped because the maximum "
            "agent iteration limit was reached."
        )

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