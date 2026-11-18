# Запуск бота

Бот запускается из корня интеграционного репозитория вместе с Go backend.
Остались два самостоятельных Compose-файла; смешивать их не нужно.

## Локальная разработка

Корневой `.env` содержит токен тестового бота и ADMIN_IDS, `targets.json` —
тестовые цели. База-копия уже подготовлена на текущей машине;
`LOCAL_DATABASE_NAME` выбирает имя базы, по умолчанию `hikari_bot_local_20261117`.
На новой машине сначала восстановите копию PostgreSQL, как описано в
`miniapp/README.md`. Автоматический импорт SQLite здесь не выполняется.

```sh
docker compose -f docker-compose.bot-local.yml up -d --build
docker compose -f docker-compose.bot-local.yml ps
docker compose -f docker-compose.bot-local.yml logs -f bot
```

Miniapp доступен на localhost:5173. Workers включены: публикации реально
отправляются. Production-токен для этого стенда не используйте.

## Сервер

Порядок подготовки `.env`, `backend/.env`, целей, сертификата и перехода
с SQLite описан в `docs/production.md` корневого репозитория.

```sh
docker compose -f docker-compose.production.yml up -d --build
docker compose -f docker-compose.production.yml logs -f bot
```

Новый бот работает только через backend; миграции изменяют PostgreSQL.
SQLite используется как источник одноразового импорта и сохраняется.
Не запускайте одновременно старого и нового бота с одним токеном.

## Остановка и обновление

Используйте тот же файл, которым запускали стенд. `stop bot` останавливает
только бота; `down` останавливает весь проект и сохраняет volumes.
Не добавляйте `-v`: в volumes хранятся PostgreSQL и снимок для импорта.
Перед обновлением сохраните базу, медиа и конфигурацию; затем пересоберите
стек командой `up -d --build` с соответствующим `-f`.
