from __future__ import annotations

import asyncio
import logging

import aiohttp
from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    ErrorEvent,
    MenuButtonCommands,
)

from .access import AdminAccess
from .miniapp_menu import configure_personal_menus
from .backend import BackendClient, BackendDatabase, BackendError
from .config import Settings
from .handlers.core import CoreHandlers
from .handlers.ai_topics import AiTopicHandlers
from .handlers.inbox import InboxHandlers
from .handlers.publications import PublicationHandlers
from .handlers.registrations import RegistrationHandlers
from .logging_middleware import UpdateLoggingMiddleware
from .runtime import AppContext
from .services.publications import PublicationService
from .services.daily_topics import DailyTopicService
from .repositories.daily_topics import DailyTopicRepository
from .workers.scheduler import SchedulerWorker
from .workers.base import BackgroundWorker

log = logging.getLogger(__name__)


class SecretaryBot:
    """Application composition root for the Telegram bot."""

    def __init__(self, settings: Settings):
        bot = Bot(settings.telegram_bot_token)
        if not settings.backend_url or not settings.backend_service_token:
            raise ValueError("Для запуска бота требуется BACKEND_URL и BOT_SERVICE_TOKEN")
        database = BackendDatabase(
            BackendClient(settings.backend_url, settings.backend_service_token)
        )
        self.context = AppContext(settings=settings, bot=bot, db=database)
        self.dispatcher = Dispatcher()
        self.dispatcher.errors.register(self._handle_backend_error)
        self.router = Router()

        access = AdminAccess(self.context)
        publication_service = PublicationService(database, settings.targets)
        topic_repository = DailyTopicRepository(database.client)
        topic_service: DailyTopicService | None = None
        if settings.ai_topics.target:
            topic_service = DailyTopicService(database.client)
        self.topic_service = topic_service
        registrations = RegistrationHandlers(self.context, access)
        publications = PublicationHandlers(
            self.context, access, publication_service
        )
        core = CoreHandlers(self.context, access, registrations)
        ai_topics = AiTopicHandlers(
            self.context, access, topic_service, topic_repository
        )
        inbox = InboxHandlers(registrations, publications, ai_topics)

        core.register(self.router)
        registrations.register(self.router)
        publications.register(self.router)
        ai_topics.register(self.router)
        # The catch-all content handler must be registered after specific commands.
        inbox.register(self.router)

        workers: list[BackgroundWorker] = [SchedulerWorker(self.context)]
        self.workers = tuple(workers)
        self.dispatcher.update.outer_middleware(UpdateLoggingMiddleware())
        self.dispatcher.include_router(self.router)

    @property
    def settings(self) -> Settings:
        return self.context.settings

    @property
    def bot(self) -> Bot:
        return self.context.bot

    @property
    def db(self) -> BackendDatabase:
        return self.context.db

    async def run(self) -> None:
        log.info(
            "Initializing backend client: backend=%s",
            self.settings.backend_url,
        )
        await self.db.initialize()
        if self.topic_service:
            await self.topic_service.refresh_capabilities()
        me = await self.bot.get_me()
        self.context.bot_username = me.username
        await self._configure_telegram_menu()
        log.info(
            "Bot initialized: id=%s username=@%s targets=%s",
            me.id,
            me.username,
            len(self.settings.targets),
        )
        worker_tasks = [
            asyncio.create_task(worker.run(), name=f"worker:{worker.name}")
            for worker in self.workers if self.settings.background_workers_enabled
        ]
        try:
            await self.dispatcher.start_polling(
                self.bot,
                allowed_updates=self.dispatcher.resolve_used_update_types(),
            )
        finally:
            for task in worker_tasks:
                task.cancel()
            await asyncio.gather(*worker_tasks, return_exceptions=True)
            close = getattr(self.db, "close", None)
            if close is not None:
                await close()
            await self.bot.session.close()

    async def _handle_backend_error(self, event: ErrorEvent) -> bool:
        exception = event.exception
        if not isinstance(exception, (BackendError, aiohttp.ClientError, asyncio.TimeoutError)):
            return False

        if isinstance(exception, BackendError) and exception.code == "capacity_limit":
            text = "Достигнут лимит backend. Попробуйте ещё раз после освобождения места."
        else:
            text = "Backend временно недоступен. Попробуйте ещё раз через несколько секунд."

        update = event.update
        if update.callback_query:
            try:
                await update.callback_query.answer(text, show_alert=True)
                return True
            except TelegramBadRequest:
                pass
        if update.message:
            await update.message.answer(text)
            return True
        return True

    async def _configure_telegram_menu(self) -> None:
        user_commands = [
            BotCommand(command="start", description="Открыть главное меню"),
            BotCommand(command="events", description="Мои мероприятия"),
            BotCommand(command="profile", description="Настройка профиля"),
        ]
        admin_commands = [
            BotCommand(command="start", description="Открыть панель администратора"),
            BotCommand(command="queue", description="Очередь публикаций"),
            BotCommand(command="registrations", description="Мероприятия и участники"),
            BotCommand(command="feedback", description="Отзывы пользователей"),
            BotCommand(command="statistics", description="Статистика людей"),
            BotCommand(command="events", description="Мои мероприятия"),
            BotCommand(command="profile", description="Настройка профиля"),
            BotCommand(command="help", description="Помощь"),
        ]
        await self.bot.set_my_commands(
            user_commands, scope=BotCommandScopeAllPrivateChats()
        )
        await self.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        await configure_personal_menus(self.bot, self.settings)
        for admin_id in self.settings.admin_ids:
            try:
                await self.bot.set_my_commands(
                    admin_commands, scope=BotCommandScopeChat(chat_id=admin_id)
                )
            except TelegramBadRequest:
                log.warning(
                    "Could not configure command menu for admin_id=%s; "
                    "the administrator may need to start the bot first",
                    admin_id,
                )
