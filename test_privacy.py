"""Перевірка приватності: `uv run python -m unittest -v`.

Особисті записи однієї людини не мають потрапити до іншої ні у звіт, ні в ліміти, ні через форму.
Працює на копії обліку в тимчасовій папці: справжні cash.beancount і limits.csv не чіпаємо.
"""
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from beancount import loader
from werkzeug.security import generate_password_hash

os.environ.setdefault("SECRET_KEY", "t" * 40)
os.environ["TRACKER_DEV"] = "1"
os.environ["TRACKER_HASH_OLIA"] = generate_password_hash("olia-pass")
os.environ["TRACKER_HASH_MARKO"] = generate_password_hash("marko-pass")

import app  # noqa: E402
import report  # noqa: E402

ROOT = Path(__file__).parent
CASH = """
2026-09-05 * "Секретний подарунок" #cash
  Expenses:Оля:Інше  80.00 PLN
  Assets:Оля:Готівка

2026-09-06 * "Спільна піца" #cash #shared
  Expenses:Оля:Кафе  40.00 PLN
  Assets:Оля:Готівка
"""


class Privacy(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        for name in ("main.beancount", "transactions.beancount"):
            shutil.copy(ROOT / name, self.dir / name)
        (self.dir / "cash.beancount").write_text(CASH, encoding="utf-8")
        (self.dir / "limits.csv").write_text("рахунок,ліміт\nExpenses:Оля:Кафе,250\n", encoding="utf-8")
        for module, name, value in [(app, "LEDGER", self.dir / "main.beancount"), (app, "CASH", self.dir / "cash.beancount"),
                                    (report, "LIMITS", self.dir / "limits.csv")]:
            old = getattr(module, name)
            setattr(module, name, value)
            self.addCleanup(setattr, module, name, old)
        app.FAILS.clear()
        self.client = app.app.test_client()

    def login(self, login):
        token = re.search(r'name="csrf" value="([^"]+)"', self.client.get("/login").text)[1]
        r = self.client.post("/login", data={"csrf": token, "login": login, "password": f"{login}-pass"})
        self.assertEqual(r.status_code, 302)
        return re.search(r'name="csrf" value="([^"]+)"', self.client.get("/add").text)[1]

    def test_visible_drops_only_other_persons_personal(self):
        entries, errors, _ = loader.load_file(str(self.dir / "main.beancount"))
        self.assertEqual(errors, [])
        for viewer in report.PEOPLE:
            for e in report.visible(entries, viewer):
                if hasattr(e, "postings"):
                    mine = any(report.owner(p.account) == viewer for p in e.postings)
                    self.assertTrue(mine or "shared" in e.tags, f"{viewer} бачить чуже: {e.narration}")

    def test_report_hides_other_persons_personal_rows(self):
        self.login("marko")
        page = self.client.get("/").text
        self.assertNotIn("Секретний подарунок", page)
        self.assertIn("Спільна піца", page)
        self.assertNotIn("Expenses:Оля", page)
        self.assertNotIn("250 зл", page)  # ліміт Олі бачить лише Оля
        self.assertIn("Марко", page)  # ім'я в шапці

    def test_owner_sees_own_personal_rows_and_limits(self):
        self.login("olia")
        page = self.client.get("/").text
        self.assertIn("Секретний подарунок", page)
        self.assertIn("з 250 зл", page)

    def test_static_report_shows_everything(self):
        page = report.render(self.dir / "main.beancount")
        self.assertIn("Секретний подарунок", page)
        self.assertNotIn("бачить лише", page)

    def test_cannot_add_cash_to_other_persons_account(self):
        token = self.login("marko")
        r = self.client.post("/add", data={"csrf": token, "amount": "10", "description": "x", "date": "2026-09-10",
                                           "account": "Expenses:Оля:Кафе", "shared": "ні"})
        self.assertIn("Оберіть категорію", r.text)
        self.assertNotIn('"x"', (self.dir / "cash.beancount").read_text(encoding="utf-8"))

    def test_cash_is_tagged_shared_by_toggle(self):
        token = self.login("marko")
        r = self.client.post("/add", data={"csrf": token, "amount": "12,50", "description": "Кава", "date": "2026-09-10",
                                           "account": "Expenses:Марко:Кафе", "shared": "так"})
        self.assertEqual(r.status_code, 302)
        self.assertIn('"Кава" #cash #shared', (self.dir / "cash.beancount").read_text(encoding="utf-8"))

    def test_limits_screen_cannot_touch_other_persons_limits(self):
        token = self.login("marko")
        self.assertNotIn("Expenses:Оля", self.client.get("/limits").text)
        r = self.client.post("/limits", data={"csrf": token, "account": "Expenses:Оля:Кафе", "amount": "1"})
        self.assertIn("Оберіть категорію", r.text)
        self.client.post("/limits", data={"csrf": token, "account": "Expenses:Марко:Кафе", "amount": "99"})
        self.assertEqual(report.load_limits(), {"Expenses:Оля:Кафе": 250, "Expenses:Марко:Кафе": 99})
        self.client.post("/limits", data={"csrf": token, "account": "Expenses:Марко:Кафе", "remove": "1"})
        self.assertEqual(report.load_limits(), {"Expenses:Оля:Кафе": 250})

    def test_no_data_without_login_and_no_fava(self):
        for path in ("/", "/add", "/limits"):
            self.assertEqual(self.client.get(path).status_code, 302)
        self.login("olia")
        self.assertEqual(self.client.get("/fava/").status_code, 404)

    def test_form_without_csrf_token_is_rejected(self):
        r = self.client.post("/login", data={"login": "olia", "password": "olia-pass"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
