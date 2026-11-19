# keitaro-wrapper

Обёртка над Keitaro Admin API. FastAPI + SQLAlchemy + Alembic, фронт на чистом HTML/JS.

Две части:

1. **Создатель кампаний.** Название, гео-код, ID оффера, домен, группа, источник. Создаёт кампанию с двумя потоками: первый ловит всех из страны и отправляет на Google, второй отправляет на оффер.
2. **Редактор кампании.** Поиск кампании, таблица офферов со статистикой из отчёта Keitaro (клики, конверсии, CR, доход, расход, прибыль, ROI, итоги), добавление, удаление офферов и ручная настройка долей.

## Запуск

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # впишите KEITARO_API_KEY
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --port 8000
```

Открыть http://localhost:8000.

API-ключ создаётся в Keitaro: Профиль, вкладка «API ключи».

## Миграции

```bash
.venv/bin/alembic upgrade head      # применить
.venv/bin/alembic downgrade -1      # откатить последнюю
```

База по умолчанию SQLite (`app.db`). Другая база: переменная `DATABASE_URL`. Новая миграция после правки `app/models.py`:

```bash
.venv/bin/alembic revision --autogenerate -m "описание"
```

Таблицы: `campaign_records` (кампании, созданные через обёртку), `offer_changes` (журнал добавления и удаления офферов).

## Настройки (.env)

| Переменная | Значение |
|---|---|
| `KEITARO_URL` | адрес Keitaro, по умолчанию `https://tlgk.host` |
| `KEITARO_API_KEY` | ключ API |
| `DATABASE_URL` | строка подключения SQLAlchemy |
| `DEFAULT_DOMAIN_ID`, `DEFAULT_GROUP_ID`, `DEFAULT_SOURCE_ID` | что выбрано в форме по умолчанию |
| `CAMPAIGN_PREFIX` | префикс названия новой кампании |
| `BASIC_AUTH_USER`, `BASIC_AUTH_PASSWORD` | если заданы, весь сервис закрыт логином и паролем |

## Как это работает

- Кампания: `POST /campaigns`, затем два `POST /streams`. Если поток не создался, кампания удаляется: пустых кампаний не остаётся.
- Поток 1: тип `regular`, фильтр `country` (accept), действие `http` на `https://google.com`.
- Поток 2: тип `default`, схема `landings`, оффер со 100% долей.
- Добавление и удаление оффера пересчитывает доли поровну (сумма всегда 100%), остаток уходит первым офферам.
- Ручная доля: меняете число в таблице, остальные офферы пересчитываются пропорционально их долям, сумма остаётся 100%.
- Keitaro не умеет искать кампании и офферы по названию через API. Обёртка забирает список целиком (кэш 30 секунд), ищет по названию или ID и листает сама («Показать ещё»).
- Цифры берутся из `POST /report/build` с группировкой по офферу и фильтром по кампании. Обёртка ничего не считает сама.
- Ошибки Keitaro (нет оффера, нет прав) показываются в интерфейсе как есть.

## API

| Метод | Путь | Что делает |
|---|---|---|
| GET | `/api/meta` | домены, группы, источники, значения по умолчанию |
| GET | `/api/offers?q=` | поиск офферов |
| POST | `/api/campaigns` | создать кампанию |
| GET | `/api/campaigns?q=&page=&per_page=` | поиск и список кампаний |
| GET | `/api/campaigns/{id}?interval=` | кампания, офферы, статистика, итоги |
| POST | `/api/campaigns/{id}/offers` | добавить оффер |
| PUT | `/api/campaigns/{id}/offers/{offer_id}` | задать долю `{"share": 40}` |
| DELETE | `/api/campaigns/{id}/offers/{offer_id}` | удалить оффер |

## Docker

```bash
cp .env.example .env        # впишите KEITARO_API_KEY
docker compose up --build   # http://localhost:8000, миграции применяются при старте
```

## Тесты

```bash
.venv/bin/python -m pytest
```

Keitaro в тестах подменён, сеть не нужна.

## Про тестовый аккаунт

Аккаунт fortests видит один оффер (18813) и не может создавать офферы. Поэтому на живом Keitaro проверены создание кампании, удаление и возврат оффера, поиск, статистика. Логика нескольких офферов (деление долей, ручная доля, пересчёт) покрыта тестами с подменённым Keitaro.
