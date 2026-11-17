#!/opt/border_bot/venv/bin/python

import re
import sys

from playwright.sync_api import sync_playwright


URL = (
    "https://granica.gov.pl/index.php/pl/"
    "tax-free/sprawdz-status-dokumentu-tax-free"
)


def solve_math(text):
    """
    Например:
    '2 + 1'
    '7-3'
    """

    text = text.replace("=", "").strip()

    m = re.search(
        r"(\d+)\s*([+\-*])\s*(\d+)",
        text
    )

    if not m:
        raise RuntimeError(
            f"Не удалось разобрать пример: {text}"
        )

    a = int(m.group(1))
    op = m.group(2)
    b = int(m.group(3))

    if op == "+":
        return str(a + b)

    if op == "-":
        return str(a - b)

    if op == "*":
        return str(a * b)

    raise RuntimeError(
        f"Неизвестный оператор: {op}"
    )


def get_vat_status(vat_number):

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )

        page = browser.new_page()

        page.goto(
            URL,
            wait_until="networkidle"
        )

        page.wait_for_timeout(3000)

        captcha_img = page.locator(
            'img[alt*="Dodaj liczby"]'
        )

        captcha_text = captcha_img.get_attribute(
            "alt"
        )

        print(
            "CAPTCHA TEXT:",
            captcha_text
        )

        m = re.search(
            r"(\d+)\s+i\s+(\d+)",
            captcha_text
        )

        if not m:
            raise RuntimeError(
                f"Не удалось разобрать капчу: {captcha_text}"
            )

        a = int(m.group(1))
        b = int(m.group(2))

        answer = str(a + b)

        print(
            "CAPTCHA:",
            a,
            "+",
            b,
            "=",
            answer
        )
           
        # Ввод номера документа
        page.locator('input[name="UNS"]').fill(
            vat_number
        )

        # Ввод ответа на капчу
        page.locator(
            'input[name="captchaAnswer"]'
        ).fill(answer)

        # Отправка формы
        page.locator(
            'input[type="submit"]'
        ).click()

        page.wait_for_timeout(5000)

        body = page.locator(
            "body"
        ).inner_text()

        if "Numer dokumentu TAX FREE:" not in body:
            status = "❌ Документ не найден"

        elif "PPotwierdzony wywóz" in body:
            status = "✅ Подтвержден вывоз"

        elif "PcPotwierdzony częściowy wywóz" in body:
            status = "🟡 Частично подтвержден вывоз"

        elif "BBrak potwierdzenia wywozu" in body:
            status = "❌ Вывоз не подтвержден"

        elif "RRozliczony z podróżnym" in body:
            status = "💰 Возврат выплачен"

        elif "ZZamknięty" in body:
            status = "🔒 Закрыт"

        elif "UUnieważniony" in body:
            status = "🚫 Аннулирован"

        elif "WWprowadzony" in body:
            status = "⏳ Введен"

        else:
            status = "❓ Статус не определён"

        return status


if __name__ == "__main__":

    import sys

    if len(sys.argv) != 2:
        print(
            "Использование:"
        )
        raise SystemExit(1)

    status = get_vat_status(
        sys.argv[1]
    )

    print()
    print(
        "TAX FREE:",
        sys.argv[1]
    )
    print(status)