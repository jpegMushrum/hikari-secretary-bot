"""Private-chat menu buttons; backend authorization remains authoritative."""
import json
import logging
from pathlib import Path

from aiogram.exceptions import TelegramAPIError
from aiogram.types import MenuButtonCommands, MenuButtonWebApp, WebAppInfo

log = logging.getLogger(__name__)


async def set_personal_menu(bot, settings, user_id):
    url = getattr(settings, 'miniapp_url', None)
    button = (MenuButtonWebApp(text='Панель клуба', web_app=WebAppInfo(url=url + '/admin/events'))
              if url and user_id in settings.admin_ids else MenuButtonCommands())
    try:
        await bot.set_chat_menu_button(chat_id=user_id, menu_button=button)
        return True
    except TelegramAPIError:
        log.warning('Could not update personal menu for user_id=%s; try /start', user_id)
        return False


async def configure_personal_menus(bot, settings):
    # Remember recipients so removing an administrator also removes their button.
    media = getattr(settings, 'media_dir', None)
    path = Path(media).parent / 'miniapp-menu-admins.json' if media else None
    previous = set()
    if path and path.exists():
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(value, list):
                previous = {v for v in value if type(v) is int}
        except (ValueError, OSError):
            log.warning('Could not read saved miniapp menu recipients')
    retained = set()
    for user_id in sorted(previous | set(settings.admin_ids)):
        ok = await set_personal_menu(bot, settings, user_id)
        if not ok or (getattr(settings, 'miniapp_url', None) and user_id in settings.admin_ids):
            retained.add(user_id)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(sorted(retained)), encoding='utf-8')
        temporary.replace(path)
