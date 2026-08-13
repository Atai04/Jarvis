import json
from typing import Any

from app.llm.base import LLMProvider
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
                result = await self._handle_tool_call(tool_call)

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

        return "JARVIS stopped because the maximum agent iteration limit was reached."

    async def _handle_tool_call(
        self,
        tool_call: Any,
    ) -> str:

        tool = self.tools.get(tool_call.name)

        if tool is None:
            return f"Unknown tool: {tool_call.name}"

        try:
            arguments = json.loads(tool_call.arguments)

        except json.JSONDecodeError as exc:
            return f"Invalid tool arguments: {exc}"

        # Dynamic permission is calculated from
        # the actual tool arguments.
        permission_level = tool.get_permission(arguments)

        if permission_level.value == "safe":
            decision = PermissionDecision.ALLOW

        elif permission_level.value == "confirm":
            decision = PermissionDecision.CONFIRM

        else:
            decision = PermissionDecision.DENY

        # ----------------------------------------
        # DENY
        # ----------------------------------------

        if decision == PermissionDecision.DENY:
            return "Action blocked by the JARVIS security policy."

        # ----------------------------------------
        # CONFIRM
        # ----------------------------------------

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
                return "The user denied the requested action."

        # ----------------------------------------
        # EXECUTE
        # ----------------------------------------

        try:
            result = await tool.execute(arguments)

        except Exception as exc:  # noqa: BLE001 - tool boundary: never crash the agent
            return f"Tool execution failed: {exc}"

        if result.success:
            return result.output

        return f"Tool execution failed: {result.error or 'Unknown error'}"

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

            working_directory = arguments.get("working_directory")

            description = f"Execute terminal command:\n  {command}"

            if working_directory:
                description += f"\nWorking directory:\n  {working_directory}"

            return description

        return f"Execute tool '{tool_name}' with arguments:\n{arguments}"
