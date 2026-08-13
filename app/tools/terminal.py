import asyncio
import os
import shlex
import subprocess
from typing import Any

from app.security.risk_analyzer import (
    CommandRisk,
    CommandRiskAnalyzer,
)
from app.tools.base import PermissionLevel, Tool, ToolResult


class TerminalTool(Tool):
    name = "terminal"

    description = (
        "Execute a single terminal command on the user's Mac. "
        "Commands are analyzed by the JARVIS security policy "
        "before execution."
    )

    # The actual permission is determined per command.
    permission = PermissionLevel.CONFIRM

    def __init__(self):
        self.risk_analyzer = CommandRiskAnalyzer()

    def schema(self) -> dict[str, Any]:

        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "A single terminal command. "
                        "Do not use command chaining, pipes, "
                        "redirects, or multiple commands."
                    ),
                },
                "working_directory": {
                    "type": ["string", "null"],
                    "description": (
                        "Optional working directory. "
                        "Use null when no specific directory is required. "
                        "Use ~ for the user's home directory."
                    ),
                },
            },
            "required": ["command", "working_directory"],
            "additionalProperties": False,
        }

    def get_permission(
        self,
        arguments: dict[str, Any],
    ) -> PermissionLevel:

        command = str(arguments.get("command", ""))

        assessment = self.risk_analyzer.analyze(command)

        if assessment.risk == CommandRisk.SAFE:
            return PermissionLevel.SAFE

        if assessment.risk == CommandRisk.CONFIRM:
            return PermissionLevel.CONFIRM

        return PermissionLevel.DANGEROUS

    async def execute(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:

        command = str(arguments.get("command", "")).strip()

        working_directory = arguments.get("working_directory")

        if not command:
            return ToolResult(
                success=False,
                output="",
                error="Command cannot be empty.",
            )

        assessment = self.risk_analyzer.analyze(command)

        # Defense in depth:
        # never execute a command that the analyzer rejects.
        if assessment.risk == CommandRisk.DENY:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Command blocked by security policy. Reason: {assessment.reason}"
                ),
            )

        try:
            parts = shlex.split(command)
        except ValueError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Invalid command syntax: {exc}",
            )

        cwd = None

        if working_directory:
            cwd = os.path.abspath(os.path.expanduser(str(working_directory)))

            if not os.path.isdir(cwd):
                return ToolResult(
                    success=False,
                    output="",
                    error=(f"Working directory does not exist: {cwd}"),
                )

        try:
            process = await asyncio.to_thread(
                subprocess.run,
                parts,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
            )

            stdout = process.stdout.strip()
            stderr = process.stderr.strip()

            if process.returncode != 0:
                return ToolResult(
                    success=False,
                    output=stdout,
                    error=(
                        stderr or (f"Command exited with code {process.returncode}.")
                    ),
                )

            return ToolResult(
                success=True,
                output=(stdout or "Command completed successfully."),
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=("Command timed out after 30 seconds."),
            )

        except FileNotFoundError:
            return ToolResult(
                success=False,
                output="",
                error=(f"Command not found: {parts[0]}"),
            )

        except Exception as exc:  # noqa: BLE001 - tool boundary: never crash the agent
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
            )
