# Проверки

Из каталога бота с установленными зависимостями:

```sh
python -m unittest discover -s tests -v
```

В Docker из корня интеграционного репозитория:

```sh
docker compose -f docker-compose.bot-local.yml run --rm --no-deps --build -v "${PWD}/bot/tests:/app/tests:ro" bot python -m unittest discover -s tests -v
```

Команда запускает тесты вместо Telegram polling. Тесты подменяют обращения
к Telegram и backend, проверяют диалоги, контракт внутреннего API, обработку
медиа, доставку и уведомления, передачу черновиков в miniapp и работу меню ИИ.
Подключение к DeepSeek и работа генератора относятся к проверкам backend.

Для проверки конфигурации или сборки используйте Compose-файл нужного стенда:

```sh
docker compose -f docker-compose.bot-local.yml config --quiet
docker compose -f docker-compose.bot-local.yml build backend bot
```

После развёртывания состояние и журналы доступны через `ps` и
`logs --tail=100 bot`. Диалоги и Web App в настоящем Telegram требуют
отдельной ручной проверки.
