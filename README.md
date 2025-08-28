# Fragment Buyer API

Автоматизированная система для покупки номеров и username'ов на платформе [Fragment](https://fragment.com).

## 🚀 Возможности

- **Мониторинг номеров**: Автоматический поиск и покупка номеров в заданном ценовом диапазоне
- **Мониторинг username'ов**: Автоматический поиск и покупка username'ов в заданном ценовом диапазоне
- **Проверка баланса**: Автоматическая проверка достаточности средств перед покупкой
- **Умная остановка**: Автоматическая остановка мониторинга при недостатке средств
- **REST API**: Полноценное API для управления системой

## 📋 Требования

- Python 3.8+
- TON кошелек с балансом
- Fragment аккаунт с cookies

## 🛠️ Установка

1. Клонируйте репозиторий:
```bash
git clone <repository-url>
cd buynumbers
```

2. Создайте виртуальное окружение:
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# или
.venv\Scripts\activate  # Windows
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Настройте переменные окружения:
```bash
# Скопируйте пример файла
cp env.example .env

# Отредактируйте .env файл с вашими данными
nano .env
```

В файле `.env` укажите:
- `SEED_PHRASE` - ваша seed фраза TON кошелька (24 слова)
- `FRAGMENT_COOKIES` - cookies от вашего Fragment аккаунта

## 🚀 Запуск

```bash
python api.py
```

Сервер запустится на `http://127.0.0.1:8000`

## 📚 API Endpoints

### Мониторинг номеров

#### Запуск мониторинга
```bash
POST /monitor-numbers/start
{
    "max_price_ton": 1000,
    "interval_sec": 1
}
```

#### Остановка мониторинга
```bash
POST /monitor-numbers/stop
```

### Мониторинг username'ов

#### Запуск мониторинга
```bash
POST /monitor-usernames/start
{
    "max_price_ton": 500,
    "interval_sec": 1
}
```

#### Остановка мониторинга
```bash
POST /monitor-usernames/stop
```

### Покупка

#### Покупка номера
```bash
POST /buy
{
    "number_id": "123456789",
    "bid_ton": 100
}
```

#### Покупка username
```bash
POST /buy-username
{
    "username_id": "example",
    "bid_ton": 50
}
```

### Информация

#### Список номеров
```bash
GET /numbers
```

#### Список username'ов
```bash
GET /usernames
```

#### Информация о кошельке
```bash
GET /wallet
```

#### Проверка здоровья
```bash
GET /health
```

## 🔧 Конфигурация

### Переменные окружения

#### Обязательные:
- `SEED_PHRASE` - Seed фраза TON кошелька (24 слова)
- `FRAGMENT_COOKIES` - Cookies от Fragment аккаунта

#### Опциональные:
- `TON_LITE_SERVER` - TON Lite Server URL (по умолчанию: mainnet_config)
- `HOST` - Хост для запуска сервера (по умолчанию: 127.0.0.1)
- `PORT` - Порт для запуска сервера (по умолчанию: 8000)
- `LOG_LEVEL` - Уровень логирования (по умолчанию: INFO)

#### Как получить Fragment cookies:
1. Войдите в аккаунт на [fragment.com](https://fragment.com)
2. Откройте Developer Tools (F12)
3. Перейдите во вкладку Application/Storage → Cookies
4. Скопируйте значения cookies: `stel_dt`, `stel_ssid`, `stel_token`, `stel_ton_token`
5. Объедините их в строку: `stel_dt=value; stel_ssid=value; stel_token=value; stel_ton_token=value`
6. Поместите всю строку в кавычки в файле `.env`

**Пример:**
```
FRAGMENT_COOKIES="stel_dt=-180; stel_ssid=your_session_id; stel_token=your_token; stel_ton_token=your_ton_token"
```

### Параметры мониторинга

- `max_price_ton` - Максимальная цена в TON
- `interval_sec` - Интервал проверки в секундах (1-60)

## 🛡️ Безопасность

- Проверка баланса перед каждой покупкой
- Предотвращение одновременных покупок
- Автоматическая остановка при недостатке средств
- Логирование всех операций

### ⚠️ Важно:
- **Никогда не коммитьте файл `.env` в git!**
- Файл `.env` уже добавлен в `.gitignore`
- Храните ваши seed фразы и cookies в безопасном месте
- Регулярно обновляйте Fragment cookies

## 📊 Логирование

Система ведет подробные логи всех операций:
- Информация о найденных товарах
- Результаты покупок
- Ошибки и предупреждения
- Состояние баланса

## 🚨 Обработка ошибок

- `400` - Неверные параметры запроса
- `402` - Недостаточно средств
- `409` - Покупка уже в процессе
- `500` - Внутренние ошибки сервера
- `504` - Таймаут операций

## 📁 Структура проекта

```
buynumbers/
├── api.py                 # Точка входа приложения
├── requirements.txt       # Зависимости
├── README.md             # Документация
├── env.example           # Пример переменных окружения
├── .env                  # Ваши переменные окружения (создать)
└── app/
    ├── main.py           # Основная логика API
    ├── clients/
    │   ├── fragment.py           # Клиент для номеров
    │   └── fragment_usernames.py # Клиент для username'ов
    ├── services/
    │   └── monitor.py    # Сервис мониторинга
    └── utils/
        └── ton.py        # Утилиты для работы с TON
```

## 👨‍💻 Разработчики

- **[Хусниддин (hoosnick)](https://github.com/hoosnick)** - Python Developer, работающий с веб-API и бэкенд-логикой
- **[Emir ~ Lycode (savamir)](https://github.com/savamir)** - Python Developer, специализирующийся на Django, FastAPI и автоматизации

## 🤝 Вклад в проект

1. Форкните репозиторий
2. Создайте ветку для новой функции
3. Внесите изменения
4. Создайте Pull Request

## 📄 Лицензия

MIT License

## ⚠️ Отказ от ответственности

Этот проект предназначен только для образовательных целей. Используйте на свой страх и риск. Авторы не несут ответственности за любые финансовые потери.
