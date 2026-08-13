import asyncio
import platform
import subprocess

from app.tools.base import PermissionLevel, Tool, ToolResult


class GetSystemInfoTool(Tool):

    name = "get_system_info"

    description = (
        "Get basic information about the current Mac, including "
        "macOS version, architecture, hostname, and Python version."
    )

    permission = PermissionLevel.SAFE

    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }

    async def execute(self, arguments: dict) -> ToolResult:
        try:
            process = await asyncio.to_thread(
                subprocess.run,
                ["sw_vers", "-productVersion"],
                capture_output=True,
                text=True,
                check=True,
            )
            macos_version = process.stdout.strip()

            hostname = platform.node()
            architecture = platform.machine()
            python_version = platform.python_version()

            output = (
                f"macOS: {macos_version}\n"
                f"Architecture: {architecture}\n"
                f"Hostname: {hostname}\n"
                f"Python: {python_version}"
            )

            return ToolResult(
                success=True,
                output=output,
            )

        except Exception as exc:  # noqa: BLE001 - tool boundary: never crash the agent
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
            )