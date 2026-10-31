# Investing Demo

Учебное Django-приложение для просмотра и ведения справочника акций: HTML-каталог,
CRUD, регистрация/вход/выход, REST API с фильтрами, поиском и сортировкой,
Django Admin, импорт справочника, график цен и фоновое обновление последней цены.

## Что проверено

- Python 3.14.7, macOS (arm64).
- Django 6.1.2, Django REST Framework 3.18.3.
- Локальный режим использует SQLite; PostgreSQL поддерживается настройками.
- Демонстрационный источник данных (`MARKET_DATA_PROVIDER=demo`) не требует
  токена и не является реальными котировками.
- Celery/Redis сохранены для фоновой работы. В проверенном окружении Redis не
  был установлен, поэтому worker/beat фактически не запускались; задача
  проверялась синхронно.

## Быстрый запуск на macOS

```bash
cd "/Users/chekalovdmitriy/aidd-topic-03-homework(Чекалов Д)/opencode"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
# При необходимости отредактируйте .env. Для локального запуска достаточно
# значений по умолчанию: SQLite и демонстрационный источник данных.

python manage.py migrate
python manage.py seed_demo_shares
python manage.py createsuperuser   # необязательно, для /admin/

python manage.py runserver
```

Откройте:

- каталог: <http://127.0.0.1:8000/>
- регистрация: <http://127.0.0.1:8000/user/registration/>
- вход: <http://127.0.0.1:8000/user/login/>
- API: <http://127.0.0.1:8000/api/v1/shares/>
- админка: <http://127.0.0.1:8000/admin/>

## Переменные окружения

Файл `.env` не коммитится. Пример без секретов — `.env.example`.

| Переменная | Назначение | Значение по умолчанию |
|---|---|---|
| `DJANGO_SECRET_KEY` | секретный ключ Django | небезопасный локальный ключ при `DEBUG=true`; обязателен при `DEBUG=false` |
| `DJANGO_DEBUG` | режим отладки | `true` |
| `DJANGO_ALLOWED_HOSTS` | разрешённые хосты через запятую | `localhost,127.0.0.1,testserver` |
| `DJANGO_TIME_ZONE` | часовой пояс Django и Celery | `Europe/Moscow` |
| `DB_ENGINE` | `sqlite` или `postgresql` | `sqlite` |
| `DB_NAME` | файл SQLite или имя БД PostgreSQL | `db.sqlite3` |
| `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | подключение PostgreSQL | `postgres`, пусто, `127.0.0.1`, `5432` |
| `MARKET_DATA_PROVIDER` | `demo` или `tinkoff` | `demo` |
| `TINKOFF_TOKEN` | токен Tinkoff Invest API | пусто |
| `PRICE_UPDATE_INTERVAL_SECONDS` | период обновления цен | `300` (5 минут) |
| `CELERY_BROKER_URL` | брокер Celery | `redis://127.0.0.1:6379/0` |
| `CELERY_TASK_ALWAYS_EAGER` | выполнять задачи синхронно | `false` |

## Источники рыночных данных

### Демонстрационный режим (по умолчанию)

`MARKET_DATA_PROVIDER=demo` использует детерминированные синтетические данные:
5 акций с тикерами `DEMOAAPL`, `DEMOMSFT`, `DEMOSBER`, `DEMOGAZP`, `DEMOYNDX`.
Их `figi`, `isin`, названия и `uid` явно помечены как демонстрационные.

- В интерфейсе показывается предупреждение «Демонстрационный источник данных».
- API возвращает заголовок `X-Market-Data-Source: demo`.
- Это **не реальные котировки** и не биржевые данные.

### Реальный провайдер Tinkoff Invest API

```dotenv
MARKET_DATA_PROVIDER=tinkoff
TINKOFF_TOKEN=ваш_токен
```

Для реального провайдера нужен дополнительный пакет. На момент проверки проект
`tinkoff-investments` на PyPI находится в карантине и не устанавливается через
`pip`; статус: <https://pypi.org/project/tinkoff-investments/>. Если доступ
восстановлен:

```bash
pip install -r requirements-tinkoff.txt
```

Альтернатива — установка из исходного репозитория (версию/коммит нужно
зафиксировать самостоятельно):

```bash
pip install "git+https://github.com/RussianInvestments/invest-python.git"
```

Интеграция с реальным провайдером реализована в
`dashboard/services/providers.py` (`TinkoffMarketDataProvider`) и не удалена.
Фактический вызов реального API в проверенном окружении не выполнялся: нет
токена, пакет недоступен на PyPI.

## Наполнение и обновление данных

Импорт справочника из выбранного источника:

```bash
python manage.py add_shares
python manage.py add_shares --provider demo
python manage.py add_shares --provider tinkoff   # нужен TINKOFF_TOKEN
```

Команда идемпотентна: повторный импорт обновляет запись по `figi`, а не создаёт
дубликат. `seed_demo_shares` — явная обёртка для демонстрационного набора.

Синхронное обновление цен (без Redis):

```bash
python manage.py shell -c "from dashboard.tasks import update_last_price; print(update_last_price.run())"
```

Фоновый режим с Celery/Redis:

```bash
# вариант с Docker Compose (если установлен Docker)
docker compose up -d redis db

# или локальный redis-server, если он установлен
redis-server

celery -A config worker -l info
celery -A config beat -l info
```

Период по умолчанию — 5 минут (`PRICE_UPDATE_INTERVAL_SECONDS=300`). Он
используется расписанием Celery Beat.

### Правила тренда и времени обновления

- `current > previous` → `is_trend_high = True` (рост);
- `current < previous` → `is_trend_high = False` (снижение);
- первое обновление (`previous is None`) или неизменная цена → `None`
  (нейтральное состояние, в интерфейсе серая ячейка);
- `updated_at` — время последнего успешного обновления цены, включая случай,
  когда цена не изменилась. Поле обновляется явно в задаче, потому что
  `QuerySet.update()` не вызывает `auto_now`;
- время хранится в UTC, отображается в часовом поясе `DJANGO_TIME_ZONE`
  (по умолчанию `Europe/Moscow`); Celery использует тот же пояс.

Цены хранятся как `DecimalField(max_digits=20, decimal_places=9)` и не теряют
дробную часть. В API значение `last_price` сериализуется DRF как строка Decimal.

## REST API

Чтение доступно всем, изменение — только аутентифицированным пользователям
(`IsAuthenticatedOrReadOnly`).

| Метод | URL | Доступ |
|---|---|---|
| `GET` | `/api/v1/shares/` | публично |
| `GET` | `/api/v1/shares/<id>/` | публично |
| `POST` | `/api/v1/shares/` | требуется вход |
| `PUT/PATCH` | `/api/v1/shares/<id>/` | требуется вход |
| `DELETE` | `/api/v1/shares/<id>/` | требуется вход |

Параметры:

- фильтры: `?name=...`, `?ticker=...`;
- поиск по префиксу имени: `?search=...`;
- сортировка: `?ordering=name`, `?ordering=-ticker`;
- пагинация: `?limit=...&offset=...`, размер страницы 100.

Примеры:

```bash
curl -s http://127.0.0.1:8000/api/v1/shares/
curl -s "http://127.0.0.1:8000/api/v1/shares/?ticker=DEMOAAPL"
curl -s "http://127.0.0.1:8000/api/v1/shares/?search=Apple&ordering=name"

# изменение: Basic Auth с email и паролем зарегистрированного пользователя
curl -u user@example.com:password \
  -X PATCH http://127.0.0.1:8000/api/v1/shares/1/ \
  -H "Content-Type: application/json" \
  -d '{"name":"Новое название"}'
```

Поле `uid` при создании через API необязательно: если не передано, генерируется
уникальное значение.

## Проверка проекта

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py test
```

Быстрая проверка запущенного сервера:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/v1/shares/
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/user/login/
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/user/registration/
```

## PostgreSQL

Локальный режим по умолчанию — SQLite. Для PostgreSQL:

```bash
docker compose up -d db
```

```dotenv
DB_ENGINE=postgresql
DB_NAME=investing
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=127.0.0.1
DB_PORT=5432
```

```bash
python manage.py migrate
```

## Структура

- `config/` — настройки Django и Celery.
- `dashboard/` — акции, HTML-представления, API, сервисы данных, команды, задачи.
- `dashboard/services/providers.py` — демонстрационный и реальный провайдеры.
- `user/` — регистрация, вход, выход.
- `ANALYSIS.md` — анализ исходной версии и отдельное описание модернизации.
- `AGENT_LOG.md` — журнал фактически выполненных команд и проверок.
