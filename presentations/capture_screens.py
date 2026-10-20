"""Снимает скриншоты Astana Walk для презентации в светлой теме (офлайн-режим чата, без фото 2ГИС).

Запуск: python capture_screens.py [--base http://127.0.0.1:8095/]
Кадры обрезаются до карты и чата, чтобы текст читался на слайде.
"""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "assets"
WHEN = "2026-10-21T12:00"


def offline(page):
    page.route("**/api/chat", lambda r: r.continue_(post_data=json.dumps({**r.request.post_data_json, "provider": "offline"})))
    page.route("**/api/pois/*/photo", lambda r: r.fulfill(status=200, content_type="application/json", body='{"available": false}'))


def ask(page, base, text):
    page.goto(base)
    page.wait_for_selector(".place-row")
    page.get_by_text("Условия прогулки", exact=True).click()
    page.locator("#when").fill(WHEN)
    page.get_by_text("Условия прогулки", exact=True).click()
    page.get_by_label("Куда хотите сходить?").fill(text)
    page.get_by_role("button", name="Отправить", exact=True).click()
    page.locator(".message.assistant .chat-place").first.wait_for(timeout=120000)
    page.wait_for_timeout(3500)


def top_of_answer(page):
    page.locator(".message.assistant").last.evaluate("e => e.scrollIntoView({block: 'start'})")
    page.wait_for_timeout(800)


def shot(page, name):
    """Map and assistant only: from the left edge of the map to the right edge of the window."""
    vw, vh = page.viewport_size["width"], page.viewport_size["height"]
    box = page.locator(".leaflet-container").first.bounding_box()
    x = max(0, box["x"] - 8)
    page.screenshot(path=str(OUT / name), clip={"x": x, "y": 0, "width": vw - x, "height": vh})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8095/")
    base = ap.parse_args().base
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in ("light",):
            page = browser.new_context(viewport={"width": 1600, "height": 900}, device_scale_factor=2,
                                       locale="ru-RU", color_scheme=theme).new_page()
            offline(page)
            capture(page, base, theme)
        browser.close()
    print("ok:", ", ".join(sorted(f.name for f in OUT.glob("demo_*.png"))))


def capture(page, base, theme):
    """Every scenario in one theme; files end with _light or _dark."""
    ask(page, base, "Я у здании Экспо 2017, хочу что-то необычное на 1–2 часа, пешком.")
    top_of_answer(page)
    shot(page, f"demo_expo_considered_{theme}.png")
    ask(page, base, "Маршрут на 2 часа от Байтерека: музей и кофе")
    shot(page, f"demo_miniroute_{theme}.png")
    ask(page, base, "Я - турист, у меня 2 часа перед вылетом: что можно посмотреть поблизости?")
    top_of_answer(page)
    shot(page, f"demo_flight_{theme}.png")
    ask(page, base, "Хочу тихое место с кофе и розеткой недалеко от Байтерека")
    page.locator(".message.assistant .chat-place").first.click()
    page.wait_for_timeout(3000)
    shot(page, f"demo_cafe_card_{theme}.png")


if __name__ == "__main__":
    main()
