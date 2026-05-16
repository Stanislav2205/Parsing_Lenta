#!/usr/bin/env python3
"""
Парсер категории "Молочные продукты" на lenta.com через Playwright.

Два режима запуска:
1) headless (браузер не открывается) - по умолчанию
2) headed (браузер видно) - флаг --headed
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import date
from pathlib import Path
from typing import TypedDict

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_URL = "https://lenta.com/catalog/molochnye-produkty-3/"
DEFAULT_COOKIES_FILE = SCRIPT_DIR / "lenta.cookies.txt"
DEFAULT_OUTPUT = SCRIPT_DIR / "lenta_molochnye_produkty.csv"
DEFAULT_EXPECTED_ADDRESS = "Санкт-Петербург, улица Савушкина, 112А"


class ProductRow(TypedDict):
    магазин: str
    дата_парсинга: str
    наименование: str
    цена: str


def first_nonempty_line(path: Path) -> str:
    if not path.is_file():
        return ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            return line
    return ""


def parse_cookie_header(cookie_header: str) -> list[dict[str, object]]:
    cookies: list[dict[str, object]] = []
    for part in cookie_header.split(";"):
        chunk = part.strip()
        if not chunk or "=" not in chunk:
            continue
        name, value = chunk.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": ".lenta.com",
                "path": "/",
                "secure": True,
            }
        )
    return cookies


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def normalize_price(text: str) -> str:
    clean = (
        text.replace("\xa0", " ")
        .replace(" ", "")
        .replace("₽", "")
        .replace("руб.", "")
        .replace("руб", "")
        .strip()
    )
    m = re.search(r"\d+(?:[.,]\d{1,2})?", clean)
    if not m:
        return ""
    return m.group(0).replace(".", ",")


def scroll_until_loaded(page, pause_ms: int = 700, stable_rounds: int = 4, max_rounds: int = 60) -> None:
    same_count = 0
    prev_cards = -1
    for _ in range(max_rounds):
        load_more = page.locator("button:has-text('Показать еще')")
        if load_more.count() > 0:
            try:
                if load_more.first.is_visible():
                    load_more.first.click(timeout=1500)
                    page.wait_for_timeout(pause_ms)
            except Exception:
                pass

        current_cards = page.locator("lu-product-card").count()
        if current_cards == prev_cards:
            same_count += 1
        else:
            same_count = 0
        if same_count >= stable_rounds:
            return
        prev_cards = current_cards
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(pause_ms)


def extract_store_label(page) -> str:
    selectors = [
        '[automation-id="street-name"]',
        '[data-qa="street-name"]',
        'button[automation-id="delivery-type-button"]',
    ]
    for selector in selectors:
        try:
            text = normalize_spaces(page.locator(selector).first.inner_text(timeout=2000))
            if text:
                return text
        except Exception:
            continue
    return "адрес не найден"


def collect_products(page) -> list[ProductRow]:
    cards = page.locator("lu-product-card")
    total = cards.count()
    rows: list[ProductRow] = []

    for idx in range(total):
        card = cards.nth(idx)
        try:
            # Используем путь к имени из DOM-структуры карточки.
            name = normalize_spaces(card.locator("xpath=.//lu-product-card-name//span/span").first.inner_text(timeout=1500))
        except Exception:
            name = ""
        if not name:
            continue

        price_text = ""
        price_selectors = [
            "xpath=.//lu-product-card-counter-manager//lu-counter//div/div[1]/span",
            "xpath=.//*[contains(@class, 'price')][1]",
            "xpath=.//span[contains(text(), '₽')][1]",
        ]
        for selector in price_selectors:
            try:
                raw = card.locator(selector).first.inner_text(timeout=800)
            except Exception:
                continue
            price_text = normalize_price(raw)
            if price_text:
                break

        rows.append(
            ProductRow(
                магазин="",
                дата_парсинга="",
                наименование=name,
                цена=price_text,
            )
        )
    return rows


def scrape(
    url: str,
    cookie_header: str,
    expected_address: str,
    headed: bool,
    timeout_sec: float,
) -> tuple[str, list[ProductRow]]:
    timeout_ms = int(timeout_sec * 1000)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
        )
        if cookie_header:
            context.add_cookies(parse_cookie_header(cookie_header))

        page = context.new_page()
        try:
            cards_loaded = False
            for attempt in range(1, 4):
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 10000))
                except PlaywrightTimeoutError:
                    pass
                try:
                    page.locator("lu-product-card").first.wait_for(timeout=12000)
                    cards_loaded = True
                    break
                except PlaywrightTimeoutError:
                    if attempt < 3:
                        page.wait_for_timeout(2000)
            if not cards_loaded:
                raise RuntimeError(
                    "Карточки товаров не загрузились. Проверьте актуальность cookie и выбранный адрес."
                )

            scroll_until_loaded(page)
            store_label = extract_store_label(page)
            if expected_address and expected_address.lower() not in store_label.lower():
                print(
                    (
                        "ПРЕДУПРЕЖДЕНИЕ: адрес в браузере не совпадает с ожидаемым. "
                        f"Ожидался: {expected_address}. Фактически: {store_label}"
                    ),
                    file=sys.stderr,
                )

            rows = collect_products(page)
            return store_label, rows
        finally:
            context.close()
            browser.close()


def write_csv(rows: list[ProductRow], output: Path, store_label: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    parsed_on = date.today().strftime("%d.%m.%Y")
    fieldnames = ["магазин", "дата парсинга", "наименование", "цена"]

    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "магазин": store_label,
                    "дата парсинга": parsed_on,
                    "наименование": row["наименование"],
                    "цена": row["цена"],
                }
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Парсер lenta.com через Playwright")
    parser.add_argument("--url", default=DEFAULT_URL, help="Стартовая страница каталога")
    parser.add_argument("--cookie", default="", help="Cookie строка в формате key=value; key2=value2")
    parser.add_argument(
        "--cookies-file",
        type=Path,
        default=DEFAULT_COOKIES_FILE,
        help="Файл с cookie-строкой (берется первая непустая строка)",
    )
    parser.add_argument(
        "--expected-address",
        default=DEFAULT_EXPECTED_ADDRESS,
        help="Ожидаемый адрес магазина (для проверки что выбрана Савушкина 112А)",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Путь к выходному CSV")
    parser.add_argument("--timeout", type=float, default=60.0, help="Таймаут операций в секундах")
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Запуск с видимым окном браузера (если не указан - headless)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cookie_header = args.cookie.strip() or first_nonempty_line(args.cookies_file)
    if not cookie_header:
        print(
            "Cookie строка не найдена. Передайте --cookie или заполните lenta.cookies.txt",
            file=sys.stderr,
        )
        return 2

    try:
        store_label, rows = scrape(
            url=args.url,
            cookie_header=cookie_header,
            expected_address=args.expected_address,
            headed=args.headed,
            timeout_sec=args.timeout,
        )
        if not rows:
            print("Товары не найдены. Проверьте cookie/доступность страницы.", file=sys.stderr)
            return 2
        write_csv(rows=rows, output=args.output, store_label=store_label)
        mode = "headed (браузер видно)" if args.headed else "headless (браузер скрыт)"
        print(f"Готово: {len(rows)} строк, режим: {mode}, файл: {args.output.resolve()}")
        return 0
    except KeyboardInterrupt:
        print("Остановлено пользователем.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

