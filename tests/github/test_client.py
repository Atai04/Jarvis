import httpx
import pytest

from app.config.settings import Settings
from app.github.client import GitHubClient


@pytest.mark.asyncio
async def test_github_client_get(monkeypatch):
    settings = Settings(github_token="test-token")
    client = GitHubClient(settings)

    async def mock_get(
        self,
        url,
        headers,
    ):
        assert url == "https://api.github.com/user"
        assert headers["Authorization"] == "Bearer test-token"

        return httpx.Response(
            200,
            json={
                "login": "test-user",
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        mock_get,
    )

    result = await client.get("/user")

    assert result["login"] == "test-user"


@pytest.mark.asyncio
async def test_github_client_get_raises_for_http_error(monkeypatch):
    settings = Settings(github_token="test-token")
    client = GitHubClient(settings)

    async def mock_get(
        self,
        url,
        headers,
    ):
        return httpx.Response(
            401,
            json={
                "message": "Bad credentials",
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        mock_get,
    )

    with pytest.raises(httpx.HTTPStatusError):
        await client.get("/user")