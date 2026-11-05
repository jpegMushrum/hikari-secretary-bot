from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import aiohttp

from .db import CapacityLimitReached, Database, Page


class BackendError(RuntimeError):
    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code
        super().__init__(f"Backend request failed: {status} {code}")


class BackendClient:
    def __init__(self, base_url: str, service_token: str):
        self.base_url = base_url.rstrip("/")
        self.service_token = service_token
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.service_token}"},
                timeout=aiohttp.ClientTimeout(total=15),
            )
        return self._session

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        session = await self._get_session()
        async with session.request(method, path, json=json, params=params) as response:
            if response.status == 204:
                return None
            try:
                payload = await response.json()
            except (aiohttp.ContentTypeError, ValueError):
                payload = {"error": "invalid_backend_response"}
            if response.status >= 400:
                raise BackendError(response.status, str(payload.get("error", "unknown")))
            return payload

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()


class BackendDatabase:
    """Remote first-slice storage with local SQLite for publishing and flows.

    SQLite remains the owner of posts, media, deliveries, AI jobs and transient
    dialogs. The completed participant/event/registration/feedback state is
    served by the Go backend.
    """

    def __init__(self, local: Database, client: BackendClient):
        self.local = local
        self.client = client

    async def initialize(self) -> None:
        await self.local.initialize()

    async def close(self) -> None:
        await self.client.close()

    def __getattr__(self, name: str):
        return getattr(self.local, name)

    @asynccontextmanager
    async def connect(self):
        async with self.local.connect() as connection:
            yield connection

    async def profile(self, user_id: int) -> dict | None:
        try:
            profile = await self.client.request(
                "GET", f"/internal/bot/v1/people/{user_id}"
            )
        except BackendError as error:
            if error.status == 404:
                return None
            raise
        # Identity synchronization creates a backend person before the first
        # registration form. Keep the old bot contract: such a technical row
        # is not yet a completed profile and must still ask for full_name.
        if (
            not profile.get("full_name")
            and profile.get("is_russian_citizen") is None
            and profile.get("is_itmo_student") is None
        ):
            return None
        return profile

    async def update_telegram_identity(
        self,
        user_id: int,
        telegram_username: str | None,
        telegram_first_name: str | None,
        telegram_last_name: str | None,
    ) -> None:
        display_name = " ".join(
            value.strip()
            for value in (telegram_first_name or "", telegram_last_name or "")
            if value and value.strip()
        ) or f"Пользователь #{user_id}"
        await self.client.request(
            "POST",
            "/internal/bot/v1/people/profile",
            json={
                "telegram_user_id": user_id,
                "username": telegram_username or "",
                "display_name": display_name,
            },
        )

    async def save_profile(
        self,
        user_id: int,
        full_name: str,
        telegram_username: str | None,
        telegram_first_name: str | None,
        telegram_last_name: str | None,
    ) -> None:
        display_name = " ".join(
            value.strip()
            for value in (telegram_first_name or "", telegram_last_name or "")
            if value and value.strip()
        ) or f"Пользователь #{user_id}"
        await self.client.request(
            "POST",
            "/internal/bot/v1/people/profile",
            json={
                "telegram_user_id": user_id,
                "username": telegram_username or "",
                "display_name": display_name,
                "full_name": full_name,
            },
        )

    async def update_profile_answers(
        self,
        user_id: int,
        *,
        is_russian_citizen: bool | None = None,
        is_itmo_student: bool | None = None,
    ) -> None:
        profile = await self.profile(user_id)
        if not profile:
            return
        await self.client.request(
            "POST",
            "/internal/bot/v1/people/profile",
            json={
                "telegram_user_id": user_id,
                "username": profile.get("telegram_username") or "",
                "display_name": profile.get("telegram_first_name") or f"Пользователь #{user_id}",
                "is_russian_citizen": is_russian_citizen,
                "is_itmo_student": is_itmo_student,
            },
        )

    async def feedback_enabled(self, user_id: int) -> bool:
        profile = await self.profile(user_id)
        return bool(profile and profile.get("feedback_enabled"))

    async def toggle_feedback_enabled(self, user_id: int) -> bool | None:
        if await self.profile(user_id) is None:
            return None
        try:
            result = await self.client.request(
                "POST", f"/internal/bot/v1/people/{user_id}/feedback/toggle"
            )
        except BackendError as error:
            if error.status == 404:
                return None
            raise
        return bool(result["feedback_enabled"])

    async def set_feedback_enabled(self, user_id: int, enabled: bool) -> bool:
        current = await self.feedback_enabled(user_id)
        if current != enabled:
            result = await self.toggle_feedback_enabled(user_id)
            return result is not None
        return True

    async def _flow(self, user_id: int, kind: str) -> dict | None:
        try:
            return await self.client.request(
                "GET", f"/internal/bot/v1/flows/{user_id}/{kind}"
            )
        except BackendError as error:
            if error.status == 404:
                return None
            raise

    async def _store_flow(
        self,
        user_id: int,
        kind: str,
        *,
        post_id: int | None = None,
        stage: str | None = None,
    ) -> None:
        await self.client.request(
            "PUT",
            f"/internal/bot/v1/flows/{user_id}/{kind}",
            json={"publication_id": post_id, "stage": stage},
        )

    async def _delete_flow(self, user_id: int, kind: str) -> None:
        await self.client.request(
            "DELETE", f"/internal/bot/v1/flows/{user_id}/{kind}"
        )

    async def begin_profile_edit(self, user_id: int) -> None:
        await self._store_flow(user_id, "profile_edit", stage="full_name")

    async def profile_edit_flow(self, user_id: int) -> dict | None:
        return await self._flow(user_id, "profile_edit")

    async def update_profile_edit(self, user_id: int, stage: str) -> None:
        await self._store_flow(user_id, "profile_edit", stage=stage)

    async def delete_profile_edit(self, user_id: int) -> None:
        await self._delete_flow(user_id, "profile_edit")

    async def begin_registration_flow(self, user_id: int, post_id: int, stage: str) -> None:
        await self._store_flow(user_id, "registration", post_id=post_id, stage=stage)

    async def registration_flow(self, user_id: int) -> dict | None:
        return await self._flow(user_id, "registration")

    async def update_registration_flow(self, user_id: int, stage: str) -> None:
        flow = await self.registration_flow(user_id)
        if flow is not None:
            await self._store_flow(
                user_id, "registration", post_id=flow.get("post_id"), stage=stage
            )

    async def delete_registration_flow(self, user_id: int) -> None:
        await self._delete_flow(user_id, "registration")

    async def set_event(
        self, post_id: int, title: str, starts_at: datetime, ends_at: datetime
    ) -> bool:
        try:
            await self.client.request(
                "POST",
                "/internal/bot/v1/events",
                json={
                    "publication_id": post_id,
                    "title": title,
                    "starts_at": starts_at.astimezone(timezone.utc).isoformat(),
                    "ends_at": ends_at.astimezone(timezone.utc).isoformat(),
                    "creator_telegram_id": 0,
                },
            )
        except BackendError as error:
            if error.code == "capacity_limit":
                raise CapacityLimitReached(5, "активных мероприятий") from error
            if error.status >= 500:
                raise
            return False
        return await self.local.set_event(post_id, title, starts_at, ends_at)

    async def remove_event(self, post_id: int) -> bool:
        try:
            await self.client.request("DELETE", f"/internal/bot/v1/events/{post_id}")
        except BackendError as error:
            if error.status == 404:
                return False
            if error.status >= 500:
                raise
            return False
        return await self.local.remove_event(post_id)

    async def mark_event_published(self, post_id: int) -> None:
        try:
            await self.client.request(
                "POST", f"/internal/bot/v1/events/{post_id}/published"
            )
        except Exception:
            # Delivery itself is already recorded locally. The scheduler's
            # reconciliation pass will retry this idempotent state update.
            return

    async def reconcile_published_events(self) -> None:
        """Retry backend publication markers after a transient API failure."""
        async with self.local.connect() as connection:
            rows = await (
                await connection.execute(
                    """SELECT DISTINCT d.post_id
                       FROM deliveries d
                       JOIN events e ON e.post_id=d.post_id
                       WHERE d.platform='telegram' AND d.status='sent'
                         AND e.status='active' AND e.starts_at>?""",
                    (datetime.now(timezone.utc).isoformat(),),
                )
            ).fetchall()
        for row in rows:
            await self.mark_event_published(int(row["post_id"]))

    async def active_events_limit_reached(self) -> bool:
        result = await self.client.request(
            "GET", "/internal/bot/v1/events", params={"view": "active_count"}
        )
        return bool(result.get("limit_reached", False))

    async def event_for_registration(self, post_id: int) -> dict | None:
        try:
            return await self.client.request("GET", f"/internal/bot/v1/events/{post_id}")
        except BackendError as error:
            if error.status == 404:
                return None
            raise

    async def available_events(self, user_id: int) -> list[dict]:
        return await self.client.request(
            "GET",
            "/internal/bot/v1/events",
            params={"view": "available", "telegram_id": user_id},
        )

    async def registration(self, user_id: int, post_id: int) -> dict | None:
        try:
            return await self.client.request(
                "GET", f"/internal/bot/v1/events/{post_id}/registrations/{user_id}"
            )
        except BackendError as error:
            if error.status == 404:
                return None
            raise

    async def register(
        self, user_id: int, post_id: int, reminder_offset_minutes: int | None
    ) -> bool:
        try:
            await self.client.request(
                "POST",
                f"/internal/bot/v1/events/{post_id}/registrations",
                json={
                    "telegram_user_id": user_id,
                    "reminder_offset_minutes": reminder_offset_minutes,
                },
            )
            return True
        except BackendError as error:
            if error.code == "capacity_limit":
                raise CapacityLimitReached(5, "активных мероприятий") from error
            if error.status >= 500:
                raise
            return False

    async def user_registrations(self, user_id: int) -> list[dict]:
        return await self.client.request(
            "GET", f"/internal/bot/v1/people/{user_id}/registrations"
        )

    async def cancel_registration(self, user_id: int, post_id: int) -> bool:
        result = await self.client.request(
            "DELETE",
            f"/internal/bot/v1/events/{post_id}/registrations/{user_id}",
        )
        return bool(result.get("cancelled"))

    async def admin_events(self, past: bool = False) -> list[dict]:
        result = await self.client.request(
            "GET", "/internal/bot/v1/events", params={"past": str(past).lower(), "page_size": 100}
        )
        return result["items"]

    async def admin_events_page(self, past: bool, page: int, page_size: int = 5) -> Page:
        result = await self.client.request(
            "GET",
            "/internal/bot/v1/events",
            params={"past": str(past).lower(), "page": page, "page_size": page_size},
        )
        return self._page(result)

    async def cancel_event(self, post_id: int) -> list[dict] | None:
        try:
            participants = await self.client.request(
                "POST", f"/internal/bot/v1/events/{post_id}/cancel"
            )
        except BackendError as error:
            if error.status == 404:
                return None
            raise
        await self.local.cancel_event(post_id)
        return participants

    async def event_registrations_page(
        self, post_id: int, page: int, page_size: int = 10, sort_by: str = "name"
    ) -> Page:
        result = await self.client.request(
            "GET",
            f"/internal/bot/v1/events/{post_id}/registrations",
            params={"page": page, "page_size": page_size, "sort": sort_by},
        )
        return self._page(result)

    async def due_reminders(self) -> list[dict]:
        return await self.client.request("GET", "/internal/bot/v1/reminders/due")

    async def mark_reminder_sent(self, user_id: int, post_id: int) -> None:
        await self.client.request(
            "POST",
            "/internal/bot/v1/reminders/mark-sent",
            json={"telegram_user_id": user_id, "publication_id": post_id},
        )

    async def due_attendance_prompts(self) -> list[dict]:
        return await self.client.request("GET", "/internal/bot/v1/attendance-prompts/due")

    async def mark_attendance_prompt_sent(self, user_id: int, post_id: int) -> None:
        await self.client.request(
            "POST",
            "/internal/bot/v1/attendance-prompts/mark-sent",
            json={"telegram_user_id": user_id, "publication_id": post_id},
        )

    async def record_attendance(self, user_id: int, post_id: int, attended: bool) -> bool:
        result = await self.client.request(
            "POST",
            "/internal/bot/v1/attendance",
            json={"telegram_user_id": user_id, "publication_id": post_id, "attended": attended},
        )
        return bool(result.get("recorded"))

    async def feedback_entry(self, feedback_id: int) -> dict | None:
        try:
            return await self.client.request("GET", f"/internal/bot/v1/feedback/{feedback_id}")
        except BackendError as error:
            if error.status == 404:
                return None
            raise

    async def feedback_entries_page(self, page: int, page_size: int = 5) -> Page:
        result = await self.client.request(
            "GET", "/internal/bot/v1/feedback", params={"page": page, "page_size": page_size}
        )
        return self._page(result)

    async def people_statistics_page(self, sort_by: str, page: int, page_size: int = 10) -> Page:
        result = await self.client.request(
            "GET",
            "/internal/bot/v1/statistics/people",
            params={"sort": sort_by, "page": page, "page_size": page_size},
        )
        # Keep the bot's existing presentation contract while the backend API
        # uses the canonical `last_visit_at` field name.
        items: list[dict] = []
        for person in result["items"]:
            item = dict(person)
            item["last_visited_at"] = item.get("last_visit_at")
            if not item.get("full_name"):
                item["full_name"] = (
                    item.get("display_name")
                    or f"Пользователь #{item.get('telegram_user_id', '—')}"
                )
            items.append(item)
        return Page(
            items=items,
            page=int(result["page"]),
            page_size=int(result["page_size"]),
            total=int(result["total"]),
        )

    async def begin_feedback_flow(self, user_id: int, post_id: int | None) -> bool:
        if post_id is not None:
            registration = await self.registration(user_id, post_id)
            if not registration or not registration.get("attended"):
                return False
        await self._store_flow(user_id, "feedback", post_id=post_id)
        return True

    async def feedback_flow(self, user_id: int) -> dict | None:
        return await self._flow(user_id, "feedback")

    async def delete_feedback_flow(self, user_id: int) -> None:
        await self._delete_flow(user_id, "feedback")

    async def save_feedback_from_flow(self, user_id: int, text: str) -> dict | None:
        flow = await self.feedback_flow(user_id)
        if not flow:
            return None
        post_id = flow.get("post_id")
        result = await self.client.request(
            "POST",
            "/internal/bot/v1/feedback",
            json={
                "telegram_user_id": user_id,
                "publication_id": post_id,
                "text": text,
            },
        )
        await self.delete_feedback_flow(user_id)
        return {"id": result["id"], "post_id": post_id}

    @staticmethod
    def _page(payload: dict) -> Page:
        return Page(
            items=payload["items"],
            page=int(payload["page"]),
            page_size=int(payload["page_size"]),
            total=int(payload["total"]),
        )
