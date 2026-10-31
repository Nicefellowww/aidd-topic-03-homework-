# Анализ проекта Investing Demo

## 0. Методика, обозначения и ограничения

Документ подготовлен по результатам **статического чтения исходного кода** ветки `agent-opencode`. Приложение не запускалось, миграции не применялись, тесты не выполнялись, подключение к PostgreSQL, Redis и Tinkoff Invest API не проверялось. Поэтому всё, что требует выполнения, помечено как предположение.

Обозначения:

- **[Ф]** — факт, непосредственно подтверждённый исходным кодом.
- **[П]** — предположение или вывод, который требует запуска/проверки.
- Ссылки на код даны в формате `путь:строка`; для краткости указываются основные места.

---

## 1. Назначение приложения и технологический стек

### 1.1. Назначение

**[Ф]** Investing Demo — учебное веб-приложение для просмотра акций и управления их справочником. Приложение:

- показывает список акций с текущей ценой и признаком роста/падения;
- показывает детальную страницу акции с графиком дневных цен за 180 дней;
- позволяет зарегистрированным пользователям создавать, редактировать и удалять записи об акциях через HTML-интерфейс;
- предоставляет REST API для CRUD-операций над акциями;
- импортирует справочник акций из Tinkoff Invest API management-командой;
- периодически обновляет последнюю цену акций фоновой задачей Celery.

Подтверждение: `dashboard/models.py:4` (`Share`), `dashboard/views.py:20-63`, `dashboard/api/v1/views.py:16`, `dashboard/management/commands/add_shares.py:8`, `dashboard/tasks.py:7`, `config/celery.py:13`.

**[П]** Приложение задумано как демонстрационный «инвестиционный дашборд», а не как полноценная торговая система: в нём нет портфелей, заявок, истории цен в БД и персональных списков наблюдения.

### 1.2. Технологический стек

| Слой | Технология | Подтверждение |
|---|---|---|
| Язык | Python | `manage.py`, `requirements.txt` |
| Web-фреймворк | Django 4.1.7 | `requirements.txt:13`, `config/settings.py:13-26` |
| REST API | Django REST Framework 3.14.0 | `requirements.txt:16`, `config/settings.py:24`, `dashboard/api/v1/views.py` |
| Фильтрация API | django-filter 22.1 | `requirements.txt:15`, `dashboard/api/v1/views.py:10-22` |
| Формы | django-crispy-forms 2.0, crispy-bootstrap3 | `requirements.txt:12-14`, `dashboard/templates/dashboard/create.html:8` |
| БД | PostgreSQL | `config/settings.py:91-104`, `docker-compose.yml:3-14` |
| Асинхронные задачи | Celery 5.2.7 | `config/celery.py`, `dashboard/tasks.py` |
| Брокер задач | Redis | `config/settings.py:141`, `docker-compose.yml:16-19` |
| Внешний рынок данных | Tinkoff Invest API (`tinkoff-investments`) | `requirements.txt:35-36`, `dashboard/services/market_data.py`, `dashboard/services/graph.py`, `dashboard/management/commands/add_shares.py` |
| Графики | Plotly 5.13.1 (серверная генерация HTML + Plotly CDN) | `requirements.txt:24`, `dashboard/services/graph.py:3-4`, `dashboard/templates/dashboard/base.html:10` |
| Драйвер БД | psycopg2-binary 2.9.5 | `requirements.txt:27` |
| Форматирование кода | black, isort | `requirements.txt:5,18` |

**[Ф]** В `INSTALLED_APPS` также подключены стандартные приложения Django: `admin`, `auth`, `contenttypes`, `sessions`, `messages`, `staticfiles` (`config/settings.py:14-19`).

---

## 2. Структура проекта и назначение основных компонентов

### 2.1. Дерево каталогов

```text
.
├── manage.py
├── requirements.txt
├── docker-compose.yml
├── README.md
├── HOMEWORK.md
├── config/                     # конфигурация Django-проекта
│   ├── settings.py
│   ├── urls.py
│   ├── celery.py
│   ├── asgi.py
│   ├── wsgi.py
│   └── __init__.py
├── dashboard/                  # основное приложение: акции, API, графики, задачи
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   ├── forms.py
│   ├── admin.py
│   ├── tasks.py
│   ├── tests.py
│   ├── api/
│   │   ├── urls.py
│   │   └── v1/
│   │       ├── router.py
│   │       ├── serializer.py
│   │       ├── urls.py
│   │       └── views.py
│   ├── management/commands/add_shares.py
│   ├── migrations/0001..0007
│   ├── services/
│   │   ├── graph.py
│   │   └── market_data.py
│   ├── static/dashboard/css/
│   └── templates/dashboard/
└── user/                       # аутентификация и регистрация
    ├── views.py
    ├── forms.py
    ├── urls.py
    ├── models.py
    ├── static/user/css/
    └── templates/user/
```

### 2.2. Назначение компонентов

| Компонент | Назначение | Подтверждение |
|---|---|---|
| `config/settings.py` | Настройки Django, БД, DRF, Celery, логирования, шаблонов | `config/settings.py` |
| `config/urls.py` | Корневая маршрутизация: admin, dashboard, user | `config/urls.py:4-8` |
| `config/celery.py` | Создание Celery-приложения и расписание Beat | `config/celery.py:7-18` |
| `dashboard/models.py` | Модель `Share` — единственная предметная сущность | `dashboard/models.py:4-21` |
| `dashboard/views.py` | HTML-представления списка, детали, создания, изменения, удаления | `dashboard/views.py` |
| `dashboard/forms.py` | ModelForm для акции | `dashboard/forms.py:6-11` |
| `dashboard/admin.py` | Регистрация `Share` в Django Admin | `dashboard/admin.py:6-19` |
| `dashboard/urls.py` | HTML-маршруты и подключение API | `dashboard/urls.py:13-20` |
| `dashboard/api/v1/views.py` | `ShareFilter` и `ShareViewSet` (CRUD API) | `dashboard/api/v1/views.py` |
| `dashboard/api/v1/serializer.py` | Сериализатор `Share` | `dashboard/api/v1/serializer.py:6-19` |
| `dashboard/api/v1/router.py` | Регистрация ViewSet в DefaultRouter | `dashboard/api/v1/router.py:5-6` |
| `dashboard/services/market_data.py` | Получение последней цены из Tinkoff API | `dashboard/services/market_data.py:6-11` |
| `dashboard/services/graph.py` | Построение графика цен за 180 дней | `dashboard/services/graph.py:11-36` |
| `dashboard/tasks.py` | Celery-задача обновления цен | `dashboard/tasks.py:7-28` |
| `dashboard/management/commands/add_shares.py` | Импорт справочника акций | `dashboard/management/commands/add_shares.py:8-24` |
| `dashboard/tests.py` | Тесты API и HTML-списка | `dashboard/tests.py:8-122` |
| `user/views.py` | Вход, регистрация, выход | `user/views.py` |
| `user/forms.py` | Формы `RegistrationForm`, `AuthForm` | `user/forms.py` |
| `user/models.py` | Алиас стандартной модели `User` | `user/models.py:1-3` |
| `dashboard/templates/dashboard/*` | Шаблоны списка, детали, формы, удаления | `dashboard/templates/dashboard/` |
| `user/templates/user/*` | Шаблоны входа и регистрации | `user/templates/user/` |

---

## 3. Архитектура и взаимодействие компонентов

### 3.1. Общая архитектура

**[Ф]** Приложение построено по типовой Django-схеме «URL → View → Model/Service → Template/Response» и использует два независимых интерфейса доступа:

1. **HTML-интерфейс** — Django-шаблоны, формы, сессии и стандартная аутентификация.
2. **REST API** — DRF `ModelViewSet`, сериализатор, пагинация, фильтрация.

**[Ф]** Слоя репозиториев и отдельного сервисного слоя для CRUD нет: представления и ViewSet напрямую работают с ORM. Выделены только сервисы для внешнего рынка данных (`dashboard/services/`).

### 3.2. Взаимодействие компонентов

```text
Браузер
  │
  ├─ GET /                         → dashboard.views.ShareListView
  │                                   → Share.objects.all()
  │                                   → dashboard/templates/dashboard/list.html
  │
  ├─ GET /<pk>                     → dashboard.views.ShareDetailView.get
  │                                   → Share.objects.get(id=pk)
  │                                   → dashboard.services.graph.get_graph(share)
  │                                        → Tinkoff Invest API (свечи за 180 дней)
  │                                        → Plotly HTML
  │                                   → dashboard/templates/dashboard/detail.html
  │
  ├─ GET/POST /create              → ShareCreateView + IsUserAuthenticatedMixin
  ├─ GET/POST /update/<pk>         → ShareUpdateView + IsUserAuthenticatedMixin
  ├─ GET/POST /delete/<pk>         → ShareDeleteView + IsUserAuthenticatedMixin
  │
  ├─ /user/login/, /user/registration/, /user/logout/
  │                                   → user.views + user.forms
  │                                   → django.contrib.auth
  │
  └─ /api/v1/shares/...            → DRF ShareViewSet
                                      → ShareSerializer
                                      → Share.objects

Celery Beat (расписание 10 секунд)
  → dashboard.tasks.update_last_price
      → для каждой Share:
          dashboard.services.market_data.get_last_data(share)
              → Tinkoff Invest API get_last_prices
          → Share.objects.filter(id=...).update(last_price, is_trend_high)

Management-команда add_shares
  → Tinkoff Invest API instruments.shares()
  → Share.objects.get_or_create(...)
```

### 3.3. Ключевые архитектурные особенности

- **[Ф]** Все HTML-страницы чтения (`/`, `/<pk>`) доступны без аутентификации; изменяющие HTML-страницы защищены миксином `IsUserAuthenticatedMixin` (`dashboard/views.py:11-17,41-63`).
- **[Ф]** REST API не задаёт собственных permission-классов, поэтому использует разрешения DRF по умолчанию (`AllowAny`). Это означает, что CRUD API доступен без аутентификации (`dashboard/api/v1/views.py:16-22`; в `config/settings.py:31-35` `DEFAULT_PERMISSION_CLASSES` не задан).
- **[Ф]** Данные о ценах не сохраняются в историю: в БД хранится только последняя цена и флаг тренда (`dashboard/models.py:13-17`). График строится каждый раз из внешнего API «на лету» (`dashboard/services/graph.py:12-20`).
- **[Ф]** Периодическое обновление цен выполняется синхронно в одной Celery-задаче: один внешний запрос на каждую акцию (`dashboard/tasks.py:9-28`).
- **[Ф]** Пользователь и акции не связаны: нет владельца акции, списка наблюдения или портфеля. Любой аутентифицированный пользователь может менять любую акцию.

---

## 4. Библиотеки, внешние сервисы и зависимости

### 4.1. Прямые зависимости

| Библиотека | Версия | Назначение в проекте |
|---|---|---|
| Django | 4.1.7 | Web-фреймворк, ORM, admin, auth, шаблоны |
| djangorestframework | 3.14.0 | REST API |
| django-filter | 22.1 | Фильтрация в API |
| django-crispy-forms | 2.0 | Рендеринг форм |
| crispy-bootstrap3 | 2022.1 | Bootstrap 3 pack для crispy |
| psycopg2-binary | 2.9.5 | Драйвер PostgreSQL |
| celery | 5.2.7 | Фоновые задачи |
| redis | 4.5.1 | Python-клиент Redis / брокер |
| tinkoff-investments | 0.2.0b50 | Клиент Tinkoff Invest API |
| tinkoff | 0.1.1 | Дополнительный пакет Tinkoff |
| plotly | 5.13.1 | Построение графиков |
| pydantic | 1.10.6 | Транзитивная зависимость Tinkoff-клиента |
| protobuf | 3.20.3 | Транзитивная зависимость gRPC/Tinkoff |
| grpcio | 1.51.3 | Транзитивная зависимость Tinkoff |
| black, isort | 23.1.0, 5.12.0 | Форматирование кода (не runtime) |

Полный список: `requirements.txt`.

### 4.2. Внешние сервисы

| Сервис | Использование | Подтверждение |
|---|---|---|
| PostgreSQL | Основное хранилище | `config/settings.py:91-104` |
| Redis | Брокер Celery | `config/settings.py:141` |
| Tinkoff Invest API | Справочник акций, последние цены, свечи | `dashboard/management/commands/add_shares.py`, `dashboard/services/market_data.py`, `dashboard/services/graph.py` |
| Plotly CDN | JS-библиотека для отображения графика | `dashboard/templates/dashboard/base.html:10` |
| CDN jQuery, Popper, Font Awesome, Moment.js, Tempus Dominus | Подключены в базовом шаблоне | `dashboard/templates/dashboard/base.html:13-24` |

### 4.3. Конфигурационные зависимости

- **[Ф]** `TINKOFF_TOKEN` хранится прямо в `config/settings.py:134` и по умолчанию пуст.
- **[Ф]** `SECRET_KEY` пуст (`config/settings.py:6`).
- **[Ф]** Параметры БД захардкожены (`config/settings.py:96-103`), переменные окружения не используются.
- **[Ф]** `DEBUG = True`, `ALLOWED_HOSTS = []` (`config/settings.py:8-10`).

---

## 5. Модель данных: сущности, атрибуты и связи

### 5.1. Сущность `Share` (акция)

Подтверждение: `dashboard/models.py:4-21`.

| Атрибут | Тип | Ограничения / особенности | Подтверждение |
|---|---|---|---|
| `id` | BigAutoField | Первичный ключ, создаётся Django | `dashboard/migrations/0001_add_share.py` |
| `figi` | CharField(255) | `unique=True` | `dashboard/models.py:7` |
| `isin` | CharField(255) | Без уникальности | `dashboard/models.py:8` |
| `name` | CharField(255) | `verbose_name="Наименование компании"` | `dashboard/models.py:9` |
| `ticker` | CharField(10) | `unique=True`, `verbose_name="Тикер"` | `dashboard/models.py:10` |
| `currency` | CharField(20) | `verbose_name="Валюта"` | `dashboard/models.py:11` |
| `uid` | CharField(255) | `unique=True`, обязательное | `dashboard/models.py:12` |
| `last_price` | FloatField | `null=True`, `blank=True` | `dashboard/models.py:13` |
| `is_trend_high` | BooleanField | `null=True`, `blank=True`; «Растет цена» | `dashboard/models.py:14-16` |
| `updated_at` | DateTimeField | `auto_now=True`, `null=True`, `blank=True` | `dashboard/models.py:17` |

Метаданные: `verbose_name = "Акция"`, `verbose_name_plural = "Акции"` (`dashboard/models.py:19-21`).

### 5.2. Сущность `User`

**[Ф]** Собственная модель пользователя отсутствует. `user/models.py` только получает стандартную модель через `get_user_model()` (`user/models.py:1-3`). Используются стандартные таблицы `auth_user`, `auth_group`, `auth_permission` и сессии Django.

**[Ф]** При регистрации email используется одновременно как `username` и как `email`: `User.objects.create_user(email, email, password)` (`user/forms.py:51`). Отдельного профиля нет.

### 5.3. Связи

- **[Ф]** Между `User` и `Share` связей нет.
- **[Ф]** Между `Share` и историей цен связей нет, так как история не хранится.
- **[Ф]** Других предметных сущностей (портфель, операция, watchlist, стратегия, уведомление) в моделях нет.

### 5.4. Ограничения целостности

- **[Ф]** `figi`, `ticker`, `uid` уникальны (`dashboard/models.py:7,10,12`).
- **[Ф]** `isin` не уникален, хотя по смыслу идентификатор ценной бумаги (`dashboard/models.py:8`).
- **[Ф]** `ticker` ограничен 10 символами (`dashboard/models.py:10`).
- **[Ф]** `last_price` хранится как `float`, а не `Decimal` (`dashboard/models.py:13`).

### 5.5. Миграции

**[Ф]** История миграций: `0001_add_share` → `0002_update_share` (уникальность `figi`, `ticker`) → `0003_add_uuid` (`uid`) → `0004_add_last_price` (`last_price`, `is_trend_high`) → `0005`/`0006` (verbose_name) → `0007_add_updated_at` (`updated_at`). Файлы: `dashboard/migrations/0001_add_share.py` … `0007_add_updated_at.py`.

---

## 6. Обработка пользовательских запросов и работа с БД

### 6.1. Маршруты

| URL | Методы | Обработчик | Доступ |
|---|---|---|---|
| `/admin/` | GET/POST | Django Admin | Требует staff-пользователя |
| `/` | GET | `ShareListView` | Публичный |
| `/<int:pk>` | GET | `ShareDetailView.get` | Публичный |
| `/create` | GET/POST | `ShareCreateView` | Только аутентифицированные |
| `/update/<int:pk>` | GET/POST | `ShareUpdateView` | Только аутентифицированные |
| `/delete/<int:pk>` | GET/POST | `ShareDeleteView` | Только аутентифицированные |
| `/api/v1/` | GET | DRF API root | Публичный |
| `/api/v1/shares/` | GET/POST | `ShareViewSet` | Публичный (см. дефекты) |
| `/api/v1/shares/<pk>/` | GET/PUT/PATCH/DELETE | `ShareViewSet` | Публичный (см. дефекты) |
| `/user/login/` | GET/POST | `AuthView` | Публичный |
| `/user/registration/` | GET/POST | `RegistrationView` | Публичный |
| `/user/logout/` | GET | `LogoutView.get` | Публичный (выход из текущей сессии) |

Подтверждение: `config/urls.py:4-8`, `dashboard/urls.py:13-20`, `dashboard/api/urls.py:3-5`, `dashboard/api/v1/urls.py:5`, `user/urls.py:7-11`.

### 6.2. HTML-запросы

1. **Список акций.** `ShareListView` (`dashboard/views.py:20-26`) делает выборку `Share.objects.all()`, сортирует по `name`, пагинирует по 100 и передаёт `share_list`/`page_obj` в `dashboard/list.html`. Шаблон выводит тикер, название, ISIN, цену, валюту; цвет ячейки зависит от `is_trend_high` (`dashboard/templates/dashboard/list.html:30-52`).
2. **Детальная страница.** `ShareDetailView.get` (`dashboard/views.py:29-38`) получает `Share` по `id`, вызывает `get_graph(share)` и рендерит `detail.html`. `get_graph` открывает `tinkoff.invest.Client`, запрашивает дневные свечи за 180 дней и формирует Plotly-разметку (`dashboard/services/graph.py:11-36`).
3. **Создание/изменение.** `ShareCreateView` и `ShareUpdateView` (`dashboard/views.py:41-55`) используют `ShareModelForm` с `fields = "__all__"` (`dashboard/forms.py:9-11`), сохраняют через стандартный `ModelForm.save()` и перенаправляют на список.
4. **Удаление.** `ShareDeleteView` (`dashboard/views.py:58-63`) показывает подтверждение (`delete.html`) и удаляет объект после POST.
5. **Защита.** `IsUserAuthenticatedMixin` проверяет `request.user.is_authenticated`; при отказе выполняется редирект на `dashboard:index` (`dashboard/views.py:11-17`).

### 6.3. Аутентификация и регистрация

- **[Ф]** `AuthView.post` (`user/views.py:16-33`) берёт `email` из `form.data`, приводит к нижнему регистру, вызывает `authenticate(username=email, password=...)`, при успехе — `login()` и редирект на список; при ошибке — рендер формы с сообщением.
- **[Ф]** `RegistrationView.post` (`user/views.py:44-55`) проверяет `form.is_valid()`, сохраняет пользователя, сразу выполняет `login()` и редирект на список.
- **[Ф]** `RegistrationForm.clean` (`user/forms.py:30-46`) проверяет совпадение паролей и отсутствие пользователя с таким email.
- **[Ф]** `RegistrationForm.save` (`user/forms.py:48-53`) создаёт пользователя через `create_user(email, email, password)` и затем аутентифицирует его.
- **[Ф]** `LogoutView.get` (`user/views.py:58-64`) вызывает `logout()` и редиректит на список.

### 6.4. REST API

- **[Ф]** `ShareViewSet` — `ModelViewSet` с queryset `Share.objects.all()` (`dashboard/api/v1/views.py:16-18`).
- **[Ф]** Сериализатор отдаёт поля `id, figi, isin, name, ticker, currency, last_price, is_trend_high, updated_at` (`dashboard/api/v1/serializer.py:9-18`).
- **[Ф]** Пагинация — `LimitOffsetPagination`, `PAGE_SIZE = 100` (`config/settings.py:31-35`).
- **[Ф]** Фильтрация — `ShareFilter` по `name`, `ticker` (`dashboard/api/v1/views.py:10-13`).
- **[Ф]** Сортировка — `ordering_fields = ["name", "ticker"]` (`dashboard/api/v1/views.py:21`).
- **[Ф]** Поиск — `SearchFilter`, `search_fields = ["$name"]` (префиксный поиск по имени) (`dashboard/api/v1/views.py:19,22`).

### 6.5. Работа с БД

- **[Ф]** Используется Django ORM; сырых SQL-запросов в проекте нет.
- **[Ф]** Чтение: `Share.objects.all()` (список, API), `Share.objects.get(id=pk)` (деталь).
- **[Ф]** Создание: `ModelForm.save()` (HTML), `ShareSerializer.save()` (API), `Share.objects.get_or_create(...)` (импорт).
- **[Ф]** Обновление: `ModelForm.save()` (HTML), `ShareSerializer.save()` (API), `Share.objects.filter(id=...).update(...)` (Celery).
- **[Ф]** Удаление: `DeleteView` (HTML), `ModelViewSet.destroy()` (API).
- **[Ф]** Миграции создают таблицу `dashboard_share`; стандартные таблицы auth создаются Django.
- **[Ф]** Транзакции явно не используются; массовое обновление цен выполняется без `atomic`.

### 6.6. Фоновые задачи

- **[Ф]** `config/celery.py:13-17` задаёт расписание `add-every-5-min` с интервалом `10.0` секунд для задачи `dashboard.tasks.update_last_price`.
- **[Ф]** `update_last_price` (`dashboard/tasks.py:7-28`) перебирает все `Share`, для каждой получает последнюю цену через `get_last_data`, вычисляет `is_trend_high` и обновляет запись через `QuerySet.update()`.
- **[Ф]** `get_last_data` (`dashboard/services/market_data.py:6-11`) вызывает `client.market_data.get_last_prices(figi=[share.figi])`, берёт `pop()` из `last_prices` и возвращает `[resp.price.units, resp.time]`.
- **[Ф]** Логирование ошибок — в логгер `main`, который пишет в консоль и файл `app.logs` (`config/settings.py:37-59`).

### 6.7. Импорт справочника акций

- **[Ф]** `add_shares` (`dashboard/management/commands/add_shares.py:8-24`) получает все акции из `client.instruments.shares()` и для каждой вызывает `Share.objects.get_or_create(figi=..., name=..., isin=..., ticker=..., currency=..., uid=...)`.

---

## 7. Восстановленные функциональные требования и пользовательские сценарии

### 7.1. Пользовательские сценарии

**Сценарий A. Просмотр справочника без авторизации**

1. Пользователь открывает `/`.
2. Система показывает постранично по 100 акций, отсортированных по названию.
3. Пользователь нажимает на тикер и открывает `/<pk>`.
4. Система показывает название, последнюю цену, валюту, время обновления и график за 180 дней.

**Сценарий B. Регистрация и вход**

1. Пользователь открывает `/user/registration/`.
2. Вводит email, пароль и подтверждение пароля.
3. При совпадении паролей и отсутствии такого email система создаёт пользователя, выполняет вход и перенаправляет на `/`.
4. В дальнейшем пользователь может выйти через `/user/logout/` и войти через `/user/login/`.

**Сценарий C. Управление акцией через HTML**

1. Аутентифицированный пользователь нажимает «Добавить» в списке.
2. Заполняет форму и сохраняет — система создаёт запись и возвращает на `/`.
3. Через кнопки «Редактировать»/«Удалить» изменяет или удаляет запись; удаление требует подтверждения.
4. Неаутентифицированный пользователь при попытке открыть `/create`, `/update/<pk>`, `/delete/<pk>` перенаправляется на `/`.

**Сценарий D. Работа через API**

1. Клиент отправляет `GET /api/v1/shares/` и получает постраничный список.
2. Может фильтровать по `name`/`ticker`, сортировать по `name`/`ticker`, искать по префиксу имени.
3. Может создать (`POST`), прочитать (`GET`), изменить (`PUT/PATCH`) и удалить (`DELETE`) акцию.

**Сценарий E. Фоновое обновление цен**

1. Celery Beat запускает задачу по расписанию.
2. Задача получает последнюю цену каждой акции из Tinkoff API.
3. Система сохраняет `last_price` и пересчитывает `is_trend_high`.
4. Список акций отображает актуальную цену и цвет тренда.

**Сценарий F. Первичное наполнение справочника**

1. Администратор/разработчик выполняет `python manage.py add_shares`.
2. Система импортирует акции из Tinkoff API в таблицу `dashboard_share`.

### 7.2. Нумерованный список функциональных требований

> Требования описывают **фактически реализованное поведение**. Дефекты и спорные решения вынесены в раздел 8 и требованиями не являются.

1. **Просмотр списка акций.** Система должна отображать список всех акций по адресу `/`.
   Подтверждение: `dashboard/views.py:20-26` (`ShareListView`), `dashboard/urls.py:14`.

2. **Пагинация списка.** Список должен выводиться страницами по 100 записей с навигацией по страницам.
   Подтверждение: `dashboard/views.py:25` (`paginate_by = 100`), `dashboard/templates/dashboard/list.html:60-80`.

3. **Сортировка списка.** Список должен быть отсортирован по названию компании.
   Подтверждение: `dashboard/views.py:26` (`ordering = ["name"]`).

4. **Состав списка.** В списке должны отображаться тикер, название, ISIN, текущая цена и валюта.
   Подтверждение: `dashboard/templates/dashboard/list.html:18-40`.

5. **Визуальный признак тренда.** Цена в списке должна подсвечиваться зелёным при `is_trend_high = True` и розовым в остальных случаях.
   Подтверждение: `dashboard/templates/dashboard/list.html:35-40`.

6. **Переход к детальной странице.** Тикер в списке должен быть ссылкой на страницу акции `/<pk>`.
   Подтверждение: `dashboard/templates/dashboard/list.html:32`, `dashboard/urls.py:15`.

7. **Детальная информация об акции.** Страница `/<pk>` должна показывать название, текущую цену, валюту и время последнего обновления.
   Подтверждение: `dashboard/views.py:29-38` (`ShareDetailView.get`), `dashboard/templates/dashboard/detail.html:11-13`.

8. **График исторических цен.** Детальная страница должна строить график дневных цен закрытия за последние 180 дней по данным Tinkoff Invest API.
   Подтверждение: `dashboard/views.py:37`, `dashboard/services/graph.py:11-36` (`get_graph`), `dashboard/templates/dashboard/detail.html:22-25`.

9. **Регистрация пользователя.** Система должна регистрировать пользователя по email и паролю, используя email как `username`.
   Подтверждение: `user/views.py:36-55` (`RegistrationView`), `user/forms.py:8-53` (`RegistrationForm`, `save`).

10. **Подтверждение пароля при регистрации.** При несовпадении `password1` и `password2` регистрация должна отклоняться с ошибкой «Введенные пароли не совпадают».
    Подтверждение: `user/forms.py:30-37` (`RegistrationForm.clean`).

11. **Уникальность email при регистрации.** Если пользователь с таким email уже существует, регистрация должна отклоняться с сообщением о занятом email.
    Подтверждение: `user/forms.py:39-46` (`RegistrationForm.clean`).

12. **Автоматический вход после регистрации.** После успешной регистрации пользователь должен быть аутентифицирован и перенаправлен на список акций.
    Подтверждение: `user/views.py:46-49`, `user/forms.py:48-53`.

13. **Вход по email и паролю.** Система должна аутентифицировать пользователя по email (в нижнем регистре) и паролю и перенаправлять на список акций.
    Подтверждение: `user/views.py:16-24` (`AuthView.post`).

14. **Сообщение об ошибке входа.** При неверных учётных данных система должна показывать сообщение «Неверный логин или пароль! Повторите попытку.» и оставаться на странице входа.
    Подтверждение: `user/views.py:25-33`.

15. **Выход из системы.** Система должна завершать сессию пользователя по `/user/logout/` и перенаправлять на список акций.
    Подтверждение: `user/views.py:58-64` (`LogoutView.get`), `user/urls.py:10`.

16. **Отображение состояния аутентификации.** В шапке сайта должен отображаться email вошедшего пользователя и кнопка «Выход»; для гостя — кнопка «Войти».
    Подтверждение: `dashboard/templates/dashboard/base.html:37-43`.

17. **Создание акции через HTML.** Аутентифицированный пользователь должен иметь возможность создать акцию через форму `/create`.
    Подтверждение: `dashboard/views.py:41-46` (`ShareCreateView`), `dashboard/forms.py:6-11` (`ShareModelForm`), `dashboard/urls.py:16`.

18. **Редактирование акции через HTML.** Аутентифицированный пользователь должен иметь возможность изменить акцию через `/update/<pk>`.
    Подтверждение: `dashboard/views.py:49-55` (`ShareUpdateView`), `dashboard/urls.py:17`.

19. **Удаление акции через HTML.** Аутентифицированный пользователь должен иметь возможность удалить акцию через `/delete/<pk>` после подтверждения.
    Подтверждение: `dashboard/views.py:58-63` (`ShareDeleteView`), `dashboard/templates/dashboard/delete.html:9-13`, `dashboard/urls.py:18`.

20. **Ограничение доступа к изменяющим HTML-страницам.** Неаутентифицированный пользователь при обращении к созданию, редактированию или удалению должен перенаправляться на список акций.
    Подтверждение: `dashboard/views.py:11-17` (`IsUserAuthenticatedMixin`), `dashboard/views.py:41,49,58`.

21. **REST API CRUD акций.** API должно поддерживать список, чтение, создание, полное и частичное изменение и удаление акций по `/api/v1/shares/` и `/api/v1/shares/<pk>/`.
    Подтверждение: `dashboard/api/v1/views.py:16-22` (`ShareViewSet`), `dashboard/api/v1/router.py:5-6`, `dashboard/api/v1/urls.py:5`.

22. **Пагинация API.** API должно использовать `LimitOffsetPagination` с размером страницы 100.
    Подтверждение: `config/settings.py:31-35`.

23. **Фильтрация API.** API должно поддерживать фильтрацию по точному значению `name` и `ticker`.
    Подтверждение: `dashboard/api/v1/views.py:10-13,20` (`ShareFilter`).

24. **Сортировка API.** API должно поддерживать сортировку по `name` и `ticker`.
    Подтверждение: `dashboard/api/v1/views.py:19,21` (`OrderingFilter`, `ordering_fields`).

25. **Поиск API.** API должно поддерживать префиксный поиск по названию компании.
    Подтверждение: `dashboard/api/v1/views.py:19,22` (`SearchFilter`, `search_fields = ["$name"]`).

26. **Состав данных API.** API должно возвращать `id`, `figi`, `isin`, `name`, `ticker`, `currency`, `last_price`, `is_trend_high`, `updated_at`.
    Подтверждение: `dashboard/api/v1/serializer.py:9-18` (`ShareSerializer.Meta.fields`).

27. **Администрирование акций.** Сотрудник должен иметь возможность просматривать, искать и редактировать акции в Django Admin.
    Подтверждение: `dashboard/admin.py:6-19` (`ShareAdmin`), `config/urls.py:5`.

28. **Импорт справочника акций.** Management-команда `add_shares` должна загружать акции из Tinkoff Invest API и сохранять их в БД.
    Подтверждение: `dashboard/management/commands/add_shares.py:8-24` (`Command.handle`).

29. **Периодическое обновление цен.** Celery-задача должна периодически получать последнюю цену каждой акции и сохранять её в `last_price`.
    Подтверждение: `config/celery.py:13-17`, `dashboard/tasks.py:7-28` (`update_last_price`), `dashboard/services/market_data.py:6-11` (`get_last_data`).

30. **Расчёт признака роста.** При обновлении цены система должна устанавливать `is_trend_high = False`, если прежняя цена больше новой, и `True` в остальных случаях.
    Подтверждение: `dashboard/tasks.py:15-22`.

31. **Логирование.** Операции получения цен и ошибки фоновой задачи должны логироваться в консоль и файл `app.logs`.
    Подтверждение: `config/settings.py:37-59`, `dashboard/services/market_data.py:10`, `dashboard/tasks.py:21,28`.

32. **Хранение данных в PostgreSQL.** Приложение должно хранить акции и пользователей в PostgreSQL.
    Подтверждение: `config/settings.py:91-104`, `docker-compose.yml:3-14`.

33. **Ограничения модели данных.** `figi`, `ticker` и `uid` должны быть уникальными; `ticker` — не длиннее 10 символов; `last_price` и `is_trend_high` могут быть пустыми.
    Подтверждение: `dashboard/models.py:7-17`.

### 7.3. Бизнес-правила и ограничения (сводка)

| Правило | Подтверждение |
|---|---|
| Просмотр списка и детальной страницы не требует входа | `dashboard/views.py:20-38` |
| Создание/изменение/удаление через HTML требует входа | `dashboard/views.py:11-17,41-63` |
| Email используется как логин | `user/forms.py:51` |
| Пароль и подтверждение должны совпадать | `user/forms.py:35-37` |
| Email при регистрации должен быть уникальным | `user/forms.py:39-46` |
| После регистрации выполняется автоматический вход | `user/views.py:46-49` |
| `figi`, `ticker`, `uid` уникальны | `dashboard/models.py:7,10,12` |
| `ticker` не длиннее 10 символов | `dashboard/models.py:10` |
| Список сортируется по `name`, по 100 на страницу | `dashboard/views.py:25-26` |
| API-страница — 100 записей | `config/settings.py:32-33` |
| API фильтрует по `name`, `ticker`, сортирует по `name`, `ticker`, ищет по префиксу `name` | `dashboard/api/v1/views.py:10-22` |
| График строится за 180 дней с дневным интервалом | `dashboard/services/graph.py:16-17` |
| Признак роста: старая цена > новой → `False`, иначе `True` | `dashboard/tasks.py:16-19` |

---

## 8. Дефекты, неоднозначности и противоречия

Ниже перечислены проблемы, которые **не являются функциональными требованиями**. Для каждой указано, подтверждена она кодом или является предположением.

### 8.1. Конфигурация и запуск

1. **[Ф] Пустой `SECRET_KEY`.** `config/settings.py:6`. Django не сможет корректно работать с криптографическими операциями (сессии, CSRF, подписи); вероятна ошибка конфигурации при запуске. Требуется проверка запуском.

2. **[Ф] Пустой `TINKOFF_TOKEN`.** `config/settings.py:134`. Без токена не работают импорт акций, обновление цен и построение графика. Обработки отсутствия токена нет.

3. **[Ф] Секреты и параметры БД захардкожены.** `config/settings.py:96-103`. Нет чтения из переменных окружения; пароль `postgres/postgres` хранится в репозитории.

4. **[Ф] `DEBUG = True` и пустой `ALLOWED_HOSTS`.** `config/settings.py:8-10`. Конфигурация непригодна для production; при `DEBUG=False` пустой `ALLOWED_HOSTS` заблокирует запросы.

5. **[Ф] В `docker-compose.yml` каталог проекта монтируется внутрь контейнера БД.** `docker-compose.yml:13-14` (`./:/app`). Это не имеет смысла для PostgreSQL и может привести к неожиданному поведению.

6. **[Ф] Нет volume для данных PostgreSQL.** `docker-compose.yml:3-14`. При пересоздании контейнера данные БД будут потеряны.

7. **[Ф] Образы `postgres` и `redis` не закреплены по версии.** `docker-compose.yml:4,17`. Повторяемость окружения не гарантирована.

8. **[Ф] Устаревшие зависимости.** `requirements.txt` фиксирует Django 4.1.7, DRF 3.14.0, Celery 5.2.7, `protobuf 3.20.3`, `grpcio 1.51.3`, `tinkoff-investments 0.2.0b50`. В текущем окружении Python 3.14.7, Django не установлен; совместимость не проверялась. **[П]** С таким набором зависимостей запуск на современном Python, вероятно, потребует модернизации.

9. **[Ф] Дублирование Tinkoff-пакетов.** `requirements.txt:35-36` содержит одновременно `tinkoff==0.1.1` и `tinkoff-investments==0.2.0b50`. **[П]** Возможен конфликт импортов/зависимостей.

10. **[Ф] Тесты требуют PostgreSQL.** `dashboard/tests.py` использует БД через `APITestCase`, а `config/settings.py` не содержит тестового профиля с SQLite. Запуск тестов без PostgreSQL не гарантирован.

### 8.2. Ошибки реализации

11. **[Ф] `ShareDetailView` возвращает 500 при несуществующем `pk`.** `dashboard/views.py:32` использует `Share.objects.get(id=pk)` без `get_object_or_404` и без обработки `DoesNotExist`.

12. **[Ф] Фоновая задача не обновляет `updated_at`.** `dashboard/tasks.py:24-26` использует `QuerySet.update()`, который не вызывает `auto_now`. В результате `updated_at` меняется только при сохранении через форму/API/админку, но не при обновлении цены. Это противоречит смыслу поля «время последнего обновления» в `detail.html:13`.

13. **[Ф] Потеря дробной части цены.** `dashboard/services/market_data.py:11` и `dashboard/services/graph.py:20` берут только `price.units` / `close.units`, игнорируя `nano`. Цены с копейками/центами будут сохраняться и отображаться как целые.

14. **[Ф] `add_shares` не является идемпотентной.** `dashboard/management/commands/add_shares.py:15-22` передаёт в `get_or_create` все поля, включая уникальный `figi`. Если акция с таким `figi` уже есть, но изменилось любое другое поле, `get_or_create` попытается создать новую запись и получит нарушение уникальности `figi`.

15. **[Ф] API-создание не передаёт `uid`.** `dashboard/api/v1/serializer.py:9-18` не включает `uid`, хотя модель требует уникальный `uid` (`dashboard/models.py:12`). **[П]** При создании через API Django подставит пустую строку; первое такое создание может пройти, второе — нарушит уникальность. Существующий тест `test_share_create` (`dashboard/tests.py:91-103`) не передаёт `uid`, но не проверялся запуском.

16. **[Ф] API не требует аутентификации.** `dashboard/api/v1/views.py:16-22` не задаёт `permission_classes`; в `config/settings.py:31-35` нет `DEFAULT_PERMISSION_CLASSES`. Любой клиент может создавать, изменять и удалять акции через API, хотя HTML-интерфейс это запрещает гостям.

17. **[Ф] HTML-форма позволяет редактировать технические поля.** `dashboard/forms.py:9-11` использует `fields = "__all__"`, поэтому в форму попадают `uid`, `last_price`, `is_trend_high`. Пользователь может вручную задать служебные значения, которые должны рассчитываться системой.

18. **[Ф] Нет проверки валидности формы входа.** `user/views.py:17-19` обращается к `form.data["email"]` и `form.data["password"]` без `form.is_valid()`. При отсутствии поля или неверном формате возможен `KeyError`/исключение вместо сообщения об ошибке.

19. **[Ф] Ошибки формы регистрации обрабатываются небезопасно.** `user/views.py:54` читает `form.errors["__all__"]`. Если ошибка относится к конкретному полю (например, неверный email), ключа `__all__` нет — возможен `KeyError`. Аналогично `user/forms.py:32-34` обращается к `cleaned_data["email"]`, которого может не быть при ошибке валидации поля.

20. **[Ф] Пароли не проходят стандартные валидаторы Django.** `RegistrationForm` — обычная `forms.Form`, а `create_user` вызывается без `validate_password` (`user/forms.py:48-53`). В результате `AUTH_PASSWORD_VALIDATORS` из `config/settings.py:106-119` не применяются.

21. **[Ф] Несогласованность регистра email.** При регистрации email сохраняется как введён (`user/forms.py:49-51`), а при входе приводится к нижнему регистру (`user/views.py:19`). Пользователь, зарегистрированный как `Foo@Bar.com`, не сможет войти, если введёт тот же email: система будет искать `foo@bar.com`.

22. **[Ф] Проверка дубликата email не атомарна и не совпадает с ограничением БД.** `user/forms.py:39-46` проверяет `User.objects.filter(email=email)`, но уникальность в БД обеспечена для `username` (email как username), а не для поля `email`. Возможны гонки и разное поведение при регистре.

23. **[Ф] Выход выполняется через GET.** `user/views.py:61-64`, `user/urls.py:10`. GET-запрос на выход может быть инициирован сторонним ресурсом (CSRF-подобный сценарий), что нежелательно.

24. **[Ф] Неверная семантика `is_trend_high` на первом обновлении.** `dashboard/tasks.py:16` сравнивает `share.last_price` с новой ценой. Если `last_price is None` (значение по умолчанию), сравнение `None > float` вызывает `TypeError`; внутренний `except` (`dashboard/tasks.py:20-22`) логирует ошибку и устанавливает `True`. То есть при первом обновлении акция всегда помечается как «растёт», даже если это не так.

25. **[Ф] Равенство цен трактуется как рост.** `dashboard/tasks.py:16-19`: при `old == new` условие `old > new` ложно, поэтому `is_trend_high = True`. Нейтрального состояния нет.

26. **[Ф] `get_last_data` не обрабатывает пустой ответ.** `dashboard/services/market_data.py:8-9` вызывает `.pop()` без проверки; при пустом `last_prices` будет `IndexError`, который перехватывается только на уровне задачи (`dashboard/tasks.py:27-28`), и акция молча пропускается.

27. **[Ф] Ошибки логируются без трассировки.** `dashboard/tasks.py:21,28` вызывает `logger.error(e)`; стек вызовов не сохраняется, диагностика затруднена.

28. **[Ф] График не кэшируется и не сохраняется.** `dashboard/services/graph.py:12-20` выполняет внешний запрос при каждом открытии детальной страницы. При недоступности Tinkoff API страница, вероятно, завершится ошибкой; обработки исключений нет. **[П]** Возможны таймауты и высокая нагрузка на API.

29. **[Ф] Нет ограничения числа внешних вызовов в фоновой задаче.** `dashboard/tasks.py:9-28` последовательно обрабатывает все акции. При большом справочнике задача может не уложиться в `CELERY_TASK_TIME_LIMIT` (30 минут, `config/settings.py:139`).

30. **[Ф] Денежные значения хранятся во `float`.** `dashboard/models.py:13`. Возможны ошибки округления; для финансовых расчётов обычно используют `Decimal`.

31. **[Ф] `isin` не уникален.** `dashboard/models.py:8`. Возможны дубликаты одной и той же бумаги с разными `figi`/`ticker`.

32. **[Ф] Ограничение `ticker` в 10 символов.** `dashboard/models.py:10`. **[П]** Для части тикеров этого может быть недостаточно; является ли ограничение намеренным — неясно.

### 8.3. Неоднозначности и противоречия

33. **[Ф] Противоречие в расписании Celery.** Имя задачи `add-every-5-min` предполагает интервал 5 минут, а фактически задано `10.0` секунд (`config/celery.py:14-16`). Неясно, какое поведение задумано.

34. **[Ф] Разные часовые пояса.** Django использует `UTC` (`config/settings.py:124`), Celery — `Europe/Moscow` (`config/settings.py:137`). Это не ошибка само по себе, но требует явного согласования при отображении времени.

35. **[Ф] Неясно, кто владеет акциями.** Все пользователи видят и редактируют один общий справочник; привязки к пользователю нет. Это может быть как осознанным решением для демо, так и дефектом проектирования.

36. **[Ф] Неясно, является ли публичный API намеренным.** HTML-интерфейс защищает изменения, API — нет. Требование к доступу API в коде не зафиксировано.

37. **[Ф] Расхождение модели и миграции для `updated_at`.** В модели `blank=True, null=True` (`dashboard/models.py:17`), в миграции `0007_add_updated_at.py` — только `auto_now=True, null=True`. На поведение БД это влияет слабо, но указывает на возможное расхождение.

38. **[Ф] Название задачи в docstring не соответствует сущности.** `ShareDeleteView` имеет docstring «Удаление задачи» (`dashboard/views.py:59`), хотя удаляет акцию. Косметический дефект.

39. **[Ф] Тестовое покрытие неполное.** Тесты есть только для `dashboard` (`dashboard/tests.py`); для `user` тестов нет. Тесты не проверяют фоновую задачу, импорт, график, обработку ошибок и права доступа API.

40. **[Ф] Проверка работоспособности не выполнялась.** В текущем окружении отсутствуют Django, PostgreSQL, Redis, Docker и токен Tinkoff. Все выводы о поведении, кроме явно подтверждённых кодом, остаются предположениями.

---

## 9. Итоговая оценка

**[Ф]** В проекте реализован базовый CRUD-справочник акций с HTML-интерфейсом, REST API, административной панелью, импортом из Tinkoff Invest API, графиком за 180 дней и фоновым обновлением последней цены.

**[Ф]** Архитектура простая: два Django-приложения, одна предметная модель, прямое использование ORM во view/viewset, два сервисных модуля для Tinkoff API и Celery-задача.

**[Ф]** Наиболее значимые риски: пустые `SECRET_KEY` и `TINKOFF_TOKEN`, отсутствие аутентификации в API, неидемпотентный импорт, некорректное обновление `updated_at`, потеря дробной части цены, ошибки обработки форм и несовместимость старых зависимостей с современным окружением. Все они требуют проверки запуском на этапе модернизации.
