# Fragment Bot 🤖

Простой бот для автоматической покупки номеров и username'ов на Fragment.

## Что умеет

- Мониторит новые номера и юзернеймы
- Покупает автоматически если цена подходит
- Следит за балансом TON кошелька
- Останавливается если денег мало
- Простое API для управления

## Что нужно

- Python 3.8+
- TON кошелек
- Аккаунт на Fragment с куками

## Установка

```bash
git clone <your-repo>
cd fragment
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

Создай `.env` файл:

```env
SEED_PHRASE="твоя seed фраза из 24 слов"
FRAGMENT_COOKIES="куки с fragment.com"
```

## Запуск

```bash
python api.py
```

Откроется на `http://127.0.0.1:8000`

## Как получить куки Fragment

1. Зайди на [fragment.com](https://fragment.com)
2. F12 → Application → Cookies
3. Скопируй: `stel_dt`, `stel_ssid`, `stel_token`, `stel_ton_token`
4. Склей в одну строку: `stel_dt=value; stel_ssid=value; ...`

## API

### Мониторинг номеров

Запуск:

```bash
POST /monitor-numbers/start
{"max_price_ton": 1000, "interval_sec": 1}
```

Остановка:

```bash
POST /monitor-numbers/stop
```

### Мониторинг юзернеймов

Запуск:

```bash
POST /monitor-usernames/start
{"max_price_ton": 500, "interval_sec": 1}
```

Остановка:

```bash
POST /monitor-usernames/stop
```

### Покупка

Номер:

```bash
POST /buy
{"number_id": "123", "bid_ton": 100}
```

Юзернейм:

```bash
POST /buy-username
{"username_id": "example", "bid_ton": 50}
```

### Инфа

```bash
GET /numbers      # список номеров
GET /usernames    # список юзернеймов
GET /wallet       # баланс кошелька
GET /health       # статус бота
```

## Важно

- Не коммить `.env` в git
- Обновляй куки периодически
- Следи за балансом кошелька

## Структура

```text
fragment/
├── api.py              # запуск
├── requirements.txt    # зависимости
└── app/
    ├── main.py         # основное API
    ├── clients/        # клиенты Fragment
    ├── services/       # мониторинг
    └── utils/          # TON утилиты
```

## Авторы

- **[hoosnick](https://github.com/hoosnick)** - бэкенд и API
- **[savamir](https://github.com/savamir)** - автоматизация и логика
