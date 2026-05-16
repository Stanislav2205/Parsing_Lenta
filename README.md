# Parsing Lenta: Playwright

Полностью переписанный парсер `lenta.com` для категории `Молочные продукты`.

Стартовый URL по умолчанию:
`https://lenta.com/catalog/molochnye-produkty-3/`

## Что делает

Скрипт `scrape_lenta_dairy.py`:
- открывает страницу каталога через Playwright;
- применяет cookies из `lenta.cookies.txt` (или `--cookie`);
- проверяет адрес магазина (по умолчанию: `Савушкина, 112А`);
- собирает наименования и цены из карточек товара;
- сохраняет CSV в `utf-8-sig`.

Колонки CSV:
- `магазин`
- `дата парсинга`
- `наименование`
- `цена`

## Установка

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m playwright install chromium
```

## Два режима запуска

### 1) Без открытия браузера (headless, по умолчанию)

```powershell
py -3 scrape_lenta_dairy.py
```

### 2) С открытием браузера (видимый режим)

```powershell
py -3 scrape_lenta_dairy.py --headed
```

## Полезные параметры

```powershell
# Явно передать cookie строкой
py -3 scrape_lenta_dairy.py --cookie "key=value; key2=value2"

# Задать другой файл cookies
py -3 scrape_lenta_dairy.py --cookies-file "D:\path\lenta.cookies.txt"

# Задать другой адрес для проверки
py -3 scrape_lenta_dairy.py --expected-address "Санкт-Петербург, улица Савушкина, 112А"

# Задать путь к выходному CSV
py -3 scrape_lenta_dairy.py --output "data\lenta_molochnye_produkty.csv"
```

