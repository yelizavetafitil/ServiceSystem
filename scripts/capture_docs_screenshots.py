"""Capture UI screenshots for user/admin guides. Requires: pip install playwright && playwright install chromium"""
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8095"
OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

VIEWPORT = {"width": 1366, "height": 900}


def shot(page, name: str):
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print("OK", path.name)


def login_personal(page, email: str, password: str):
    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.locator("#form-personal input[name=email]").fill(email)
    page.locator("#form-personal input[name=password]").fill(password)
    page.locator("#form-personal button[type=submit]").click()
    page.wait_for_load_state("networkidle")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, locale="ru-RU")
        page = context.new_page()

        page.goto(f"{BASE}/login", wait_until="networkidle")
        shot(page, "01-login")

        login_personal(page, "kozlov@brestenergo.by", "customer123")
        for url, name in [
            ("/cabinet/", "02-cabinet-dashboard"),
            ("/cabinet/plugins", "03-cabinet-plugins"),
            ("/cabinet/tutorials", "04-cabinet-tutorials"),
            ("/cabinet/videos", "05-cabinet-videos"),
            ("/tickets/", "06-tickets-list"),
            ("/tickets/new", "07-ticket-create"),
        ]:
            page.goto(BASE + url, wait_until="networkidle")
            shot(page, name)

        page.goto(f"{BASE}/logout", wait_until="networkidle")

        login_personal(page, "admin@belnipi.by", "admin123")
        for url, name in [
            ("/admin/", "10-admin-dashboard"),
            ("/admin/contracts", "11-admin-contracts"),
            ("/admin/routing", "12-admin-routing"),
            ("/admin/users", "13-admin-users"),
            ("/admin/plugins", "14-admin-plugins"),
            ("/admin/audit", "15-admin-audit"),
        ]:
            page.goto(BASE + url, wait_until="networkidle")
            shot(page, name)

        page.goto(f"{BASE}/logout", wait_until="networkidle")
        login_personal(page, "auditor@belnipi.by", "auditor123")
        page.goto(f"{BASE}/tickets/staff", wait_until="networkidle")
        shot(page, "20-auditor-queue")

        browser.close()


if __name__ == "__main__":
    main()
