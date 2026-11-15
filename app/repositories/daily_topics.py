from __future__ import annotations

from ..backend import BackendClient
from ..services.daily_topics import TopicGenerationOptions


class DailyTopicRepository:
    """Durable AI queue accessed exclusively through the private backend API."""

    def __init__(self, client: BackendClient):
        self.client = client

    async def preferences(self) -> TopicGenerationOptions:
        data = await self.client.request(
            "GET", "/internal/bot/v1/ai-topics/preferences"
        )
        return TopicGenerationOptions(data["jlpt_level"], data.get("admin_comment"))

    async def save_preferences(self, options: TopicGenerationOptions, updated_by: int) -> None:
        await self.client.request(
            "PUT",
            "/internal/bot/v1/ai-topics/preferences",
            json={
                "jlpt_level": options.jlpt_level,
                "admin_comment": options.admin_comment,
                "updated_by": updated_by,
            },
        )
