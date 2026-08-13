import asyncio
import subprocess

from app.tools.base import PermissionLevel, Tool, ToolResult


class OpenApplicationTool(Tool):

    name = "open_application"
    description = (
        "Open an installed macOS application by its exact application name. "
        "Use this when the user explicitly asks JARVIS to open an application."
    )
    permission = PermissionLevel.SAFE

    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "application_name": {
                    "type": "string",
                    "description": "The exact name of the macOS application to open.",
                }
            },
            "required": ["application_name"],
            "additionalProperties": False,
        }

    async def execute(self, arguments: dict) -> ToolResult:
        application_name = arguments["application_name"].strip()

        if not application_name:
            return ToolResult(
                success=False,
                output="",
                error="Application name cannot be empty.",
            )

        try:
            process = await asyncio.to_thread(
                subprocess.run,
                ["open", "-a", application_name],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            if process.returncode != 0:
                error = process.stderr.strip() or "macOS failed to open the application."

                return ToolResult(
                    success=False,
                    output="",
                    error=error,
                )

            return ToolResult(
                success=True,
                output=f"Successfully opened {application_name}.",
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="Opening the application timed out.",
            )

        except Exception as exc:  # noqa: BLE001 - tool boundary: never crash the agent
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
            )