# Проверки

Полный набор тестов запускается в контейнере, без доступа к рабочей базе и
реальным Telegram API:

```bash
docker compose -f docker-compose.bot-local.yml run --rm --no-deps -v "${PWD}/bot:/app" bot \
  python -m unittest discover -s tests -v
```

Тесты покрывают публикации и очередь доставки, регистрации,
посещаемость, отзывы, административные таблицы, AI-очередь и обработку ошибок
DeepSeek.

Перед изменением или выпуском также проверьте конфигурацию Compose:

```bash
docker compose -f docker-compose.bot-local.yml config --quiet
docker compose -f docker-compose.bot-local.yml build backend bot
```

После развёртывания просмотрите состояние контейнеров и последние логи:

```bash
docker compose -f docker-compose.bot-local.yml ps
docker compose -f docker-compose.bot-local.yml logs --tail=100 bot
```
