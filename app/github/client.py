import httpx

from app.config.settings import Settings


class GitHubClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.github_token:
            raise ValueError("GITHUB_TOKEN is not configured.")

        self.token = settings.github_token
        self.base_url = "https://api.github.com"

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def get(
        self,
        path: str,
    ) -> dict:
        url = f"{self.base_url}{path}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=self._headers(),
            )

        response.raise_for_status()

        return response.json()