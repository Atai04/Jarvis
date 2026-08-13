import pytest

from app.github.tools import InspectRepositoryTool, ListRepositoriesTool
from app.tools.base import PermissionLevel


@pytest.mark.asyncio
async def test_inspect_repository():
    class FakeGitHubClient:
        async def get(self, path: str):
            assert path == "/repos/Atai04/atai-portfolio"

            return {
                "name": "atai-portfolio",
                "full_name": "Atai04/atai-portfolio",
                "private": False,
                "description": "Personal portfolio",
                "html_url": "https://github.com/Atai04/atai-portfolio",
                "default_branch": "main",
                "language": "TypeScript",
                "stargazers_count": 5,
                "forks_count": 1,
            }

    tool = InspectRepositoryTool(FakeGitHubClient())

    result = await tool.execute(
        {
            "owner": "Atai04",
            "repository": "atai-portfolio",
        }
    )

    assert result.success is True
    assert "Atai04/atai-portfolio" in result.output
    assert "Personal portfolio" in result.output
    assert "TypeScript" in result.output


@pytest.mark.asyncio
async def test_inspect_repository_permission_is_safe():
    class FakeGitHubClient:
        async def get(self, path: str):
            return {}

    tool = InspectRepositoryTool(FakeGitHubClient())

    assert tool.permission == PermissionLevel.SAFE


def test_inspect_repository_schema():
    class FakeGitHubClient:
        async def get(self, path: str):
            return {}

    tool = InspectRepositoryTool(FakeGitHubClient())

    schema = tool.schema()

    assert schema["type"] == "object"
    assert "owner" in schema["properties"]
    assert "repository" in schema["properties"]
    assert schema["required"] == ["owner", "repository"]
    assert schema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_inspect_repository_requires_owner():
    class FakeGitHubClient:
        async def get(self, path: str):
            raise AssertionError("GitHub should not be called")

    tool = InspectRepositoryTool(FakeGitHubClient())

    result = await tool.execute(
        {
            "owner": "",
            "repository": "test-repo",
        }
    )

    assert result.success is False
    assert result.error == "Repository owner is required."


@pytest.mark.asyncio
async def test_inspect_repository_requires_repository():
    class FakeGitHubClient:
        async def get(self, path: str):
            raise AssertionError("GitHub should not be called")

    tool = InspectRepositoryTool(FakeGitHubClient())

    result = await tool.execute(
        {
            "owner": "Atai04",
            "repository": "",
        }
    )

    assert result.success is False
    assert result.error == "Repository name is required."


@pytest.mark.asyncio
async def test_list_repositories():
    class FakeGitHubClient:
        async def get(self, path: str):
            assert path == "/user/repos?sort=updated&per_page=100"

            return [
                {
                    "name": "atai-portfolio",
                    "full_name": "Atai04/atai-portfolio",
                    "private": False,
                    "description": "Personal portfolio",
                    "html_url": "https://github.com/Atai04/atai-portfolio",
                },
                {
                    "name": "smart-waste-sorter",
                    "full_name": "Atai04/smart-waste-sorter",
                    "private": False,
                    "description": "AI waste sorting system",
                    "html_url": (
                        "https://github.com/Atai04/smart-waste-sorter"
                    ),
                },
            ]

    tool = ListRepositoriesTool(FakeGitHubClient())

    result = await tool.execute({})

    assert result.success is True
    assert "Atai04/atai-portfolio" in result.output
    assert "Atai04/smart-waste-sorter" in result.output
    assert "Personal portfolio" in result.output
    assert "AI waste sorting system" in result.output


@pytest.mark.asyncio
async def test_list_repositories_empty():
    class FakeGitHubClient:
        async def get(self, path: str):
            assert path == "/user/repos?sort=updated&per_page=100"
            return []

    tool = ListRepositoriesTool(FakeGitHubClient())

    result = await tool.execute({})

    assert result.success is True
    assert result.output == "No GitHub repositories found."


def test_list_repositories_permission_is_safe():
    class FakeGitHubClient:
        async def get(self, path: str):
            return []

    tool = ListRepositoriesTool(FakeGitHubClient())

    assert tool.permission == PermissionLevel.SAFE


def test_list_repositories_schema():
    class FakeGitHubClient:
        async def get(self, path: str):
            return []

    tool = ListRepositoriesTool(FakeGitHubClient())

    schema = tool.schema()

    assert schema["type"] == "object"
    assert schema["properties"] == {}
    assert schema["required"] == []
    assert schema["additionalProperties"] is False
