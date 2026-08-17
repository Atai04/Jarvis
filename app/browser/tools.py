from typing import Any
from urllib.parse import urlparse

import httpx

from app.tools.base import PermissionLevel, Tool, ToolResult


class OpenURLTool(Tool):
    name = "open_url"
    description = (
        "Open a public HTTP or HTTPS URL and return the webpage content "
        "as plain text. Use this when the user explicitly asks to open "
        "or inspect a specific web page."
    )
    permission = PermissionLevel.SAFE

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The HTTP or HTTPS URL to open.",
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        url = str(arguments.get("url", "")).strip()

        if not url:
            return ToolResult(
                success=False,
                output="",
                error="URL is required.",
            )

        parsed = urlparse(url)

        if not parsed.netloc:
            return ToolResult(
                success=False,
                output="",
                error="A valid URL is required.",
            )

        if parsed.scheme not in {"http", "https"}:
            return ToolResult(
                success=False,
                output="",
                error="Only HTTP and HTTPS URLs are supported.",
            )

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=15.0,
            ) as client:
                response = await client.get(
                    url,
                    headers={
                        "User-Agent": "JARVIS/1.0",
                    },
                )

            response.raise_for_status()

            content_type = response.headers.get(
                "content-type",
                "",
            ).lower()

            if "text" not in content_type and "json" not in content_type:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        "The URL does not return a supported text "
                        "or JSON response."
                    ),
                )

            content = response.text.strip()

            if not content:
                return ToolResult(
                    success=True,
                    output="The page returned no text content.",
                )

            max_length = 20_000

            if len(content) > max_length:
                content = (
                    content[:max_length]
                    + "\n\n[Content truncated by JARVIS.]"
                )

            return ToolResult(
                success=True,
                output=content,
            )

        except httpx.HTTPStatusError as exc:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"HTTP request failed with status "
                    f"{exc.response.status_code}."
                ),
            )

        except httpx.RequestError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Request failed: {exc}",
            )

        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
            )