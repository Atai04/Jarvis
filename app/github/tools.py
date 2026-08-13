from typing import Any

from app.github.client import GitHubClient
from app.tools.base import PermissionLevel, Tool, ToolResult


class InspectRepositoryTool(Tool):
    name = "inspect_repository"
    description = (
        "Inspect a GitHub repository and return its basic metadata, "
        "including description, visibility, default branch, language, "
        "stars, forks, and URL."
    )
    permission = PermissionLevel.SAFE

    def __init__(self, client: GitHubClient) -> None:
        self.client = client

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "GitHub repository owner or organization.",
                },
                "repository": {
                    "type": "string",
                    "description": "GitHub repository name.",
                },
            },
            "required": [
                "owner",
                "repository",
            ],
            "additionalProperties": False,
        }

    async def execute(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        owner = str(arguments.get("owner", "")).strip()
        repository = str(arguments.get("repository", "")).strip()

        if not owner:
            return ToolResult(
                success=False,
                output="",
                error="Repository owner is required.",
            )

        if not repository:
            return ToolResult(
                success=False,
                output="",
                error="Repository name is required.",
            )

        try:
            data = await self.client.get(
                f"/repos/{owner}/{repository}",
            )

            visibility = "private" if data.get("private") else "public"

            output = "\n".join(
                [
                    f"Repository: {data.get('full_name', f'{owner}/{repository}')}",
                    f"Description: {data.get('description') or 'No description'}",
                    f"Visibility: {visibility}",
                    f"Default branch: {data.get('default_branch', 'unknown')}",
                    f"Language: {data.get('language') or 'unknown'}",
                    f"Stars: {data.get('stargazers_count', 0)}",
                    f"Forks: {data.get('forks_count', 0)}",
                    f"URL: {data.get('html_url', '')}",
                ]
            )

            return ToolResult(
                success=True,
                output=output,
            )

        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
            )


class ListRepositoriesTool(Tool):
    name = "list_repositories"
    description = (
        "List repositories accessible to the authenticated GitHub user. "
        "Returns repository names, visibility, descriptions, and URLs."
    )
    permission = PermissionLevel.SAFE

    def __init__(self, client: GitHubClient) -> None:
        self.client = client

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }

    async def execute(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        try:
            repositories = await self.client.get(
                "/user/repos?sort=updated&per_page=100",
            )

            if not repositories:
                return ToolResult(
                    success=True,
                    output="No GitHub repositories found.",
                )

            lines = []

            for repository in repositories:
                visibility = (
                    "private"
                    if repository.get("private")
                    else "public"
                )

                lines.append(
                    f"- {repository.get('full_name', 'unknown')} "
                    f"({visibility}) — "
                    f"{repository.get('description') or 'No description'}"
                )

            return ToolResult(
                success=True,
                output="\n".join(lines),
            )

        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
            )
