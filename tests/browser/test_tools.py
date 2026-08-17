import pytest

from app.browser.tools import OpenURLTool
from app.tools.base import PermissionLevel


@pytest.mark.asyncio
async def test_open_url_requires_url():
    tool = OpenURLTool()

    result = await tool.execute({})

    assert result.success is False
    assert result.error == "URL is required."


@pytest.mark.asyncio
async def test_open_url_rejects_invalid_scheme():
    tool = OpenURLTool()

    result = await tool.execute(
        {
            "url": "ftp://example.com",
        }
    )

    assert result.success is False
    assert result.error == "Only HTTP and HTTPS URLs are supported."


@pytest.mark.asyncio
async def test_open_url_rejects_invalid_url():
    tool = OpenURLTool()

    result = await tool.execute(
        {
            "url": "not-a-url",
        }
    )

    assert result.success is False
    assert result.error == "A valid URL is required."


def test_open_url_is_safe():
    tool = OpenURLTool()

    assert tool.permission == PermissionLevel.SAFE


def test_open_url_schema():
    tool = OpenURLTool()

    schema = tool.schema()

    assert schema["type"] == "object"
    assert "url" in schema["properties"]
    assert schema["required"] == ["url"]
    assert schema["additionalProperties"] is False