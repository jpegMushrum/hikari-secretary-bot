# Запуск бота

Выполняйте команды из корня
[интеграционного репозитория](https://github.com/jpegMushrum/hikari-secretary).
Выберите Compose-файл своего окружения.

## Локальная разработка

Подготовьте корневые `.env` и `targets.json` по примерам. Задайте
`TELEGRAM_BOT_TOKEN` тестового бота, числовые `ADMIN_IDS` через запятую
и тестовые цели публикаций.

`LOCAL_DATABASE_NAME` указывает имя заранее подготовленной базы в
PostgreSQL локального стека. По умолчанию Compose ожидает копию
`hikari_bot_local_20261117` в volume проекта `hikari-miniapp-dev`. На новой
машине задайте `LOCAL_DATABASE_NAME=hikari_dev`, чтобы использовать пустую
базу, которую создаёт PostgreSQL при первичной инициализации volume. Сервис
`migrate` применит к выбранной базе миграции. Для работы на копии данных
предварительно восстановите её под выбранным именем.

```sh
docker compose -f docker-compose.bot-local.yml up -d --build
docker compose -f docker-compose.bot-local.yml ps
docker compose -f docker-compose.bot-local.yml logs -f bot
```

Miniapp доступен на [localhost:5173](http://localhost:5173). Бот запускается
с включённой фоновой доставкой и отправляет сообщения в заданные цели.
Compose отключает открытие miniapp из Telegram. Для генерации тем ИИ
задайте ключ DeepSeek и тестовую цель по [руководству по ИИ-материалам](ai-materials.md).

## Production

[Инструкция развёртывания](https://github.com/jpegMushrum/hikari-secretary/blob/main/docs/production.md)
описывает подготовку корневого `.env`, `backend/.env`, целей публикаций,
сертификата и импорт из старой SQLite.

```sh
docker compose -f docker-compose.production.yml up -d --build
docker compose -f docker-compose.production.yml logs -f bot
```

Миграции обновляют PostgreSQL. Одноразовый импорт старых данных запускается
отдельно через профиль `legacy-import`. Перед запуском нового бота остановите
предыдущий экземпляр с тем же Telegram-токеном.

## Остановка и обновление

Используйте тот же Compose-файл, которым запускали стенд. Команда `stop bot`
останавливает бота, а `down` останавливает весь стек. Сохраняйте volumes
PostgreSQL и снимка SQLite и каталог медиа на хосте. Перед обновлением сохраните
базу, медиа и конфигурацию. Для пересборки используйте `up -d --build`.
