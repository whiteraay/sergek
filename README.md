# Sergek — AFO AI Developer Internship Test Assignment

**Сбор данных о парковках Алматы из 2ГИС + WhatsApp-рассыльщик**

---

## Структура проекта

```
sergek/
├── task1/
│   ├── data/
│   │   ├── parkings_almaty.csv        # сырые данные (выход scraper.py)
│   │   └── parkings_almaty_clean.csv  # очищенные данные (выход clean_data.py)
│   ├── scraper.py                     # сбор данных из 2ГИС по районам
│   ├── clean_data.py                  # очистка и обогащение CSV
│   └── upload_to_sheets.py            # загрузка в Google Sheets
├── task2/
│   ├── whatsapp_sender.py             # рассыльщик (dry-run + live)
│   └── contacts.csv                   # свой номер для live-демо
├── ANKET.md                           # анкета + описание решений
├── requirements.txt
└── README.md
```

---

## Быстрый старт (5 минут)

### Установка зависимостей

```bash
pip install -r requirements.txt
playwright install chromium
```

---

## Задача 1 — Парсер 2ГИС

### Шаг 1: Собрать данные

```bash
cd task1
python scraper.py
# Выход: data/parkings_almaty.csv (~818 строк)
```


### Шаг 2: Очистить и обогатить данные

```bash
python clean_data.py
# Вход:  data/parkings_almaty.csv
# Выход: data/parkings_almaty_clean.csv
```

Что делает скрипт:
- Удаляет дубликаты по `id`
- Заполняет пустые `district`, `paid`, `parking_type` по названию и адресу
- Унифицирует координаты
- Добавляет колонку `google_maps_url`
- Нормализует часы работы
- Сортирует по району и типу

### Шаг 3: Загрузить в Google Sheets

```bash
python upload_to_sheets.py --sheets-id YOUR_SPREADSHEET_ID
# Читает data/parkings_almaty_clean.csv и загружает в таблицу
```

> **Настройка** — см. раздел «Google Sheets Setup» ниже.

---

## Задача 2 — WhatsApp Sender

### Dry-run (по умолчанию, ничего не отправляет)

```bash
cd task2
python whatsapp_sender.py ../task1/data/parkings_almaty_clean.csv
# Все сообщения записываются в dry_run_messages.log
```

### Live-режим (отправка на свой номер)

```bash
# 1. Открыть contacts.csv, вписать свой номер в формате 77XXXXXXXXXX
# 2. Запустить:
python whatsapp_sender.py contacts.csv --live
# Откроется браузер → сканировать QR телефоном → отправит 2 сообщения
```

С кастомным шаблоном:
```bash
python whatsapp_sender.py contacts.csv --live \
  --template "Парковка: {name}, адрес: {address}, часы: {hours}"
```

---

## Поля в данных

| Поле | Описание |
|------|----------|
| `id` | ID объекта в 2ГИС |
| `name` | Название парковки |
| `address` | Адрес |
| `city` / `district` | Город / район |
| `lat` / `lon` | GPS-координаты |
| `url_2gis` | Ссылка на 2gis.kz |
| `google_maps_url` | Ссылка на Google Maps |
| `parking_type` | БЦ / ТЦ/ТРК / городская / ЖК / отель / автостоянка / частная |
| `paid` | Платная / бесплатная / вероятно платная |
| `tariff` | Тариф (если есть в 2ГИС) |
| `capacity` | Количество мест (если есть) |
| `parent_object` | Объект, которому принадлежит парковка |
| `hours` | Часы работы или "24/7" |
| `rating` | Рейтинг на 2ГИС |
| `review_count` | Количество отзывов |
| `has_photos` | Есть ли фото |

---

## Google Sheets Setup

1. Открыть [console.cloud.google.com](https://console.cloud.google.com)
2. Создать проект → включить **Google Sheets API** и **Google Drive API**
3. IAM & Admin → Service Accounts → Create → скачать JSON-ключ
4. Сохранить ключ как `task1/service_account.json`
5. Открыть Google Sheet → Поделиться → вставить email сервисного аккаунта → Editor
6. Запустить `upload_to_sheets.py`

---

## Подход и технические решения

### Почему Playwright + перехват сетевых ответов?

2ГИС блокирует прямые запросы к `catalog.api.2gis.com` — API требует сессионные куки и ключ, привязанный к домену. Прямые `requests` возвращают 403.

**Решение:** запускаем Chromium через Playwright, открываем страницы поиска 2ГИС и перехватываем JSON-ответы через `page.on("response", ...)`. Браузер авторизован — данные приходят в структурированном виде без парсинга HTML.

**Почему по районам?** Поисковый эндпоинт 2ГИС обрезает выдачу на ~100 объектах. Разбивка по 8 районам Алматы даёт 800+ уникальных записей.

**Альтернативы, которые рассматривали:**
- Официальный API 2ГИС → 403, ключ привязан к домену
- DOM-скрапинг → хрупкий, CSS-классы меняются при деплое
- Replay заголовков из DevTools → токены сессии живут минуты

### Обработка ошибок

- Невалидные телефоны → `skipped`, скрипт продолжает работу
- Таймаут по району → перехватывается, остальные районы обрабатываются
- Дубликаты → дедупликация по `id` объекта 2ГИС
- Квота Google Sheets API → загрузка чанками по 500 строк с паузами