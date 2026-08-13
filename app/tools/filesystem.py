from pathlib import Path

from app.tools.base import PermissionLevel, Tool, ToolResult

ALLOWED_ROOTS = [
    Path.home(),
    Path("/tmp"),
]


def normalize_path(raw_path: str) -> Path:
    r"""
    Normalize common path formats before resolving them.

    Examples:
        ~/jarvis
        \~/jarvis
        /Users/example/jarvis
    """

    path = raw_path.strip()

    # Some interfaces escape "~" as "\~".
    if path.startswith(r"\~"):
        path = path[1:]

    return Path(path).expanduser()


def is_allowed_path(path: Path) -> bool:
    try:
        resolved = path.resolve()

        return any(
            resolved == root.resolve() or root.resolve() in resolved.parents
            for root in ALLOWED_ROOTS
        )

    except OSError:
        return False


class ListDirectoryTool(Tool):
    name = "list_directory"

    description = (
        "List files and directories inside a permitted directory. "
        "Use this when the user asks JARVIS to inspect a folder."
    )

    permission = PermissionLevel.SAFE

    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Directory path to inspect. "
                        "Paths beginning with ~ refer to the user's home directory."
                    ),
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        }

    async def execute(self, arguments: dict) -> ToolResult:
        raw_path = arguments["path"]
        requested_path = normalize_path(raw_path)

        if not is_allowed_path(requested_path):
            return ToolResult(
                success=False,
                output="",
                error=(f"Access to this path is not permitted: {requested_path}"),
            )

        try:
            if not requested_path.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Directory does not exist: {requested_path}",
                )

            if not requested_path.is_dir():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Not a directory: {requested_path}",
                )

            entries = sorted(
                requested_path.iterdir(),
                key=lambda item: (not item.is_dir(), item.name.lower()),
            )

            if not entries:
                return ToolResult(
                    success=True,
                    output="Directory is empty.",
                )

            lines = []

            for entry in entries:
                prefix = "[DIR]" if entry.is_dir() else "[FILE]"
                lines.append(f"{prefix} {entry.name}")

            return ToolResult(
                success=True,
                output="\n".join(lines),
            )

        except PermissionError:
            return ToolResult(
                success=False,
                output="",
                error=f"Permission denied: {requested_path}",
            )

        except Exception as exc:   # noqa: BLE001 - tool boundary: never crash the agent
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
            )


class ReadFileTool(Tool):
    name = "read_file"

    description = (
        "Read a UTF-8 text file from a permitted location. "
        "Use this when the user asks JARVIS to inspect a local file."
    )

    permission = PermissionLevel.SAFE

    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Path to the text file. Use ~ for the user's home directory."
                    ),
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        }

    async def execute(self, arguments: dict) -> ToolResult:
        raw_path = arguments["path"]
        requested_path = normalize_path(raw_path)

        if not is_allowed_path(requested_path):
            return ToolResult(
                success=False,
                output="",
                error=(f"Access to this path is not permitted: {requested_path}"),
            )

        try:
            if not requested_path.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"File does not exist: {requested_path}",
                )

            if not requested_path.is_file():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Not a file: {requested_path}",
                )

            content = requested_path.read_text(encoding="utf-8")

            return ToolResult(
                success=True,
                output=content,
            )

        except UnicodeDecodeError:
            return ToolResult(
                success=False,
                output="",
                error=f"File is not valid UTF-8: {requested_path}",
            )

        except PermissionError:
            return ToolResult(
                success=False,
                output="",
                error=f"Permission denied: {requested_path}",
            )

        except Exception as exc:   # noqa: BLE001 - tool boundary: never crash the agent
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
            )
