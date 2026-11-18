import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SetChatMenuButton
from app.miniapp_menu import configure_personal_menus, set_personal_menu
from app.handlers.core import CoreHandlers
from app.access import AdminAccess


class MiniappMenuTests(unittest.TestCase):
    def test_start_refreshes_menu_without_breaking_registration_link(self):
        settings = SimpleNamespace(admin_ids={1}, miniapp_url='https://club.example')
        bot = SimpleNamespace(set_chat_menu_button=AsyncMock())
        context = SimpleNamespace(settings=settings, bot=bot)
        registrations = SimpleNamespace(begin_registration=AsyncMock())
        handler = CoreHandlers(context, AdminAccess(context), registrations)
        message = SimpleNamespace(from_user=SimpleNamespace(id=2), chat=SimpleNamespace(type='private'), text='/start event_42', answer=AsyncMock())
        asyncio.run(handler.start(message))
        self.assertEqual(bot.set_chat_menu_button.await_args.kwargs['menu_button'].type, 'commands')
        registrations.begin_registration.assert_awaited_once_with(message.from_user, message.answer, 42)

    def test_only_admin_gets_webapp_and_port_is_preserved(self):
        bot = SimpleNamespace(set_chat_menu_button=AsyncMock())
        settings = SimpleNamespace(admin_ids={1}, miniapp_url='https://hikari.jpegmushrum.ru:8443')
        asyncio.run(set_personal_menu(bot, settings, 1))
        args = bot.set_chat_menu_button.await_args.kwargs
        self.assertEqual(args['chat_id'], 1)
        self.assertEqual(args['menu_button'].web_app.url, 'https://hikari.jpegmushrum.ru:8443/admin/events')
        asyncio.run(set_personal_menu(bot, settings, 2))
        self.assertEqual(bot.set_chat_menu_button.await_args.kwargs['menu_button'].type, 'commands')
        settings.miniapp_url = None
        asyncio.run(set_personal_menu(bot, settings, 1))
        self.assertEqual(bot.set_chat_menu_button.await_args.kwargs['menu_button'].type, 'commands')

    def test_removed_admin_menu_is_reset_on_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = Path(folder) / 'miniapp-menu-admins.json'
            registry.write_text('[2]')
            settings = SimpleNamespace(admin_ids={1}, miniapp_url='https://club.example', media_dir=Path(folder) / 'media')
            bot = SimpleNamespace(set_chat_menu_button=AsyncMock())
            asyncio.run(configure_personal_menus(bot, settings))
            calls = {c.kwargs['chat_id']: c.kwargs['menu_button'].type for c in bot.set_chat_menu_button.await_args_list}
            self.assertEqual(calls, {1: 'web_app', 2: 'commands'})
            self.assertEqual(json.loads(registry.read_text()), [1])

    def test_unavailable_chat_is_retried_and_does_not_block_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = Path(folder) / 'miniapp-menu-admins.json'
            registry.write_text('[2]')
            settings = SimpleNamespace(admin_ids=set(), miniapp_url=None, media_dir=Path(folder) / 'media')
            bot = SimpleNamespace(set_chat_menu_button=AsyncMock(side_effect=TelegramBadRequest(method=SetChatMenuButton(), message='chat not found')))
            asyncio.run(configure_personal_menus(bot, settings))
            self.assertEqual(json.loads(registry.read_text()), [2])
