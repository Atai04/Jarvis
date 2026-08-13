from typing import Any

from app.memory.repository import MemoryRepository
from app.tools.base import PermissionLevel, Tool, ToolResult


class RememberPreferenceTool(Tool):
    name = "remember_preference"

    description = (
        "Save a user preference or fact to long-term memory as a key/value pair. "
        "Use this when the user explicitly asks JARVIS to remember something "
        "(e.g. 'remember that my favorite project is X'). "
        "If the key already exists, its value is updated."
    )

    permission = PermissionLevel.SAFE

    def __init__(self, memory: MemoryRepository) -> None:
        self.memory = memory

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": (
                        "Short, stable identifier for this preference, "
                        "e.g. 'favorite_project'."
                    ),
                },
                "value": {
                    "type": "string",
                    "description": "The value to remember for this key.",
                },
            },
            "required": ["key", "value"],
            "additionalProperties": False,
        }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        key = str(arguments.get("key", "")).strip()
        value = str(arguments.get("value", "")).strip()

        if not key:
            return ToolResult(
                success=False,
                output="",
                error="Preference key cannot be empty.",
            )

        if not value:
            return ToolResult(
                success=False,
                output="",
                error="Preference value cannot be empty.",
            )

        try:
            updated = self.memory.update_preference(key, value)

            if not updated:
                self.memory.save_preference(key, value)

        except Exception as exc:  # noqa: BLE001 - tool boundary: never crash the agent
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
            )

        return ToolResult(
            success=True,
            output=f"Remembered: {key} = {value}",
        )


class GetPreferenceTool(Tool):
    name = "get_preference"

    description = (
        "Retrieve a previously remembered user preference or fact by key "
        "from long-term memory. Use this when the user asks about something "
        "they previously told JARVIS to remember."
    )

    permission = PermissionLevel.SAFE

    def __init__(self, memory: MemoryRepository) -> None:
        self.memory = memory

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": (
                        "The identifier of the preference to retrieve, "
                        "e.g. 'favorite_project'."
                    ),
                },
            },
            "required": ["key"],
            "additionalProperties": False,
        }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        key = str(arguments.get("key", "")).strip()

        if not key:
            return ToolResult(
                success=False,
                output="",
                error="Preference key cannot be empty.",
            )

        try:
            value = self.memory.get_preference(key)
        except Exception as exc:  # noqa: BLE001 - tool boundary: never crash the agent
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
            )

        if value is None:
            return ToolResult(
                success=False,
                output="",
                error=f"No preference found for key '{key}'.",
            )

        return ToolResult(
            success=True,
            output=value,
        )


class RememberProjectTool(Tool):
    name = "remember_project"

    description = (
        "Save or update information about a project in long-term memory. "
        "Use this when the user explicitly asks JARVIS to remember a project "
        "and what it's about (e.g. 'remember that smart-waste-sorter is my "
        "capstone project using ESP32-CAM'). "
        "If the project already exists, its description is updated."
    )

    permission = PermissionLevel.SAFE

    def __init__(self, memory: MemoryRepository) -> None:
        self.memory = memory

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": (
                        "Short, stable identifier for the project, "
                        "e.g. 'smart-waste-sorter'."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": (
                        "What the project is about, its current state, "
                        "or any relevant detail to remember."
                    ),
                },
            },
            "required": ["project_name", "description"],
            "additionalProperties": False,
        }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        project_name = str(arguments.get("project_name", "")).strip()
        description = str(arguments.get("description", "")).strip()

        if not project_name:
            return ToolResult(
                success=False,
                output="",
                error="Project name cannot be empty.",
            )

        if not description:
            return ToolResult(
                success=False,
                output="",
                error="Project description cannot be empty.",
            )

        try:
            updated = self.memory.update_project(project_name, description)

            if not updated:
                self.memory.save_project(project_name, description)

        except Exception as exc:  # noqa: BLE001 - tool boundary: never crash the agent
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
            )

        return ToolResult(
            success=True,
            output=f"Remembered project '{project_name}': {description}",
        )


class GetProjectTool(Tool):
    name = "get_project"

    description = (
        "Retrieve previously remembered information about a project by name "
        "from long-term memory. Use this when the user asks about a project "
        "they previously told JARVIS to remember."
    )

    permission = PermissionLevel.SAFE

    def __init__(self, memory: MemoryRepository) -> None:
        self.memory = memory

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": (
                        "The identifier of the project to retrieve, "
                        "e.g. 'smart-waste-sorter'."
                    ),
                },
            },
            "required": ["project_name"],
            "additionalProperties": False,
        }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        project_name = str(arguments.get("project_name", "")).strip()

        if not project_name:
            return ToolResult(
                success=False,
                output="",
                error="Project name cannot be empty.",
            )

        try:
            project = self.memory.get_project(project_name)
        except Exception as exc:  # noqa: BLE001 - tool boundary: never crash the agent
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
            )

        if project is None:
            return ToolResult(
                success=False,
                output="",
                error=f"No project found with name '{project_name}'.",
            )

        description = project.get("description") or "(no description)"

        return ToolResult(
            success=True,
            output=f"{project_name}: {description}",
        )