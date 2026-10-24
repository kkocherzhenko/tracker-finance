"""Веб-застосунок для телефону: окремий вхід для Олі й Марка, звіт, готівка, ліміти.

Кожен бачить свої записи і лише спільні (#shared) записи іншої людини (report.visible).
Fava у веб-застосунку немає: її редактор показує сирі файли обліку з чужими особистими записами.

Налаштування лише через змінні середовища (див. README):
- SECRET_KEY         — випадковий ключ для підпису cookie сесії;
- TRACKER_HASH_OLIA, TRACKER_HASH_MARKO — хеші паролів (створює make_env.py);
- TRACKER_DEV=1   — лише для запуску на своєму комп'ютері: дозволяє http без HTTPS.
"""
import csv
import fcntl
import hmac
import io
import os
import re
import secrets
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from beancount import loader
from beancount.core import data
from flask import Flask, abort, redirect, request, send_from_directory, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

import cashbook
import report

ROOT = Path(__file__).parent
LEDGER = ROOT / "main.beancount"
CASH = ROOT / "cash.beancount"
STATIC = ROOT / "static"
WARSAW = ZoneInfo("Europe/Warsaw")
DEV = os.environ.get("TRACKER_DEV") == "1"

SECRET_KEY = os.environ.get("SECRET_KEY", "")
if len(SECRET_KEY) < 32:
    raise RuntimeError("SECRET_KEY не задано (або коротший за 32 символи). Див. README.")
LOGINS = {"olia": "Оля", "marko": "Марко"}  # логін -> людина в обліку
USERS = {login: h for login in LOGINS if (h := os.environ.get(f"TRACKER_HASH_{login.upper()}"))}

app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=not DEV,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
cashbook.ensure(CASH)

# ----- Захист від підбору пароля: 5 невдалих спроб з однієї адреси -> пауза 5 хвилин -----
FAILS = {}  # ip -> (кількість, час першої невдачі)
MAX_FAILS, LOCK_SECONDS = 5, 300


def locked(ip):
    count, since = FAILS.get(ip, (0, 0))
    if time.time() - since > LOCK_SECONDS:
        FAILS.pop(ip, None)
        return False
    return count >= MAX_FAILS


def note_fail(ip):
    count, since = FAILS.get(ip, (0, time.time()))
    FAILS[ip] = (count + 1, since)


# Хеш-заглушка, щоб перевірка невідомого логіна тривала стільки ж, як і відомого.
DUMMY_HASH = "scrypt:32768:8:1$x$" + "0" * 128


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf():
    expected = session.get("csrf", "")
    if not expected or not hmac.compare_digest(request.form.get("csrf", ""), expected):
        abort(400, "Форма застаріла, оновіть сторінку.")


PUBLIC = {"login", "static_file", "manifest", "service_worker"}


@app.before_request
def require_login():
    if request.endpoint not in PUBLIC and session.get("user") not in LOGINS:
        return redirect(url_for("login"))


def me():
    """Людина в обліку, яка зараз увійшла: Оля або Марко."""
    return LOGINS[session["user"]]


@app.after_request
def no_store(response):
    if request.endpoint not in {"static_file", "manifest", "service_worker"}:
        response.headers["Cache-Control"] = "no-store"
    return response


# ----- Сторінки -----
HEAD = """
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="/static/icon-192.png">
<link rel="apple-touch-icon" href="/static/apple-touch-icon.png">
<meta name="theme-color" content="#0071e3">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Фінанси">
<script>if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js');</script>"""


def page(title, body):
    return f"""<!doctype html>
<html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>{HEAD}
<style>{report.CSS}
form .field {{ display:block; margin:0 0 16px; }} form .field > span {{ display:block; color:var(--ink2); font-size:.9rem; margin-bottom:4px; }}
input, select {{ font:inherit; font-size:1.05rem; width:100%; padding:12px 14px; border-radius:12px; border:1px solid var(--line); background:var(--surface); color:var(--ink); }}
.radios {{ display:flex; gap:8px; }} .radios label {{ flex:1; }} .radios label {{ position:relative; }} .radios input {{ position:absolute; inset:0; width:100%; height:100%; margin:0; opacity:0; }}
.radios span {{ display:block; text-align:center; padding:10px; border-radius:12px; background:var(--seg); cursor:pointer; }}
.radios input:checked + span {{ background:var(--accent); color:#fff; font-weight:600; }}
.radios input:focus-visible + span {{ outline:2px solid var(--accent); outline-offset:2px; }}
.btn.wide {{ width:100%; padding:14px; font-size:1.05rem; }}
.error {{ background:var(--warn); border-radius:12px; padding:10px 14px; }}
</style></head><body><main>{body}</main></body></html>"""


def nav():
    return f"""<details class="menu"><summary class="btn ghost" aria-label="Меню">{me()} ▾</summary>
<div class="menu-list"><a href="{url_for('add')}">+ Готівка</a><a href="{url_for('limits')}">Ліміти</a>
<form method="post" action="{url_for('logout')}"><input type="hidden" name="csrf" value="{csrf_token()}">
<button type="submit">Вийти</button></form></div></details>"""


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        check_csrf()
        ip = request.remote_addr or "?"
        if locked(ip):
            error = "Забагато невдалих спроб. Спробуйте за 5 хвилин."
        else:
            name = request.form.get("login", "").strip().lower()
            stored = USERS.get(name)
            ok = check_password_hash(stored or DUMMY_HASH, request.form.get("password", ""))
            if stored and ok:
                FAILS.pop(ip, None)
                session.clear()
                session.permanent = True
                session["user"] = name
                return redirect(url_for("index"))
            note_fail(ip)
            error = "Неправильний логін або пароль."
    if not USERS:
        error = "Вхід ще не налаштовано: на сервері немає хешів паролів (make_env.py)."
    return page("Вхід", f"""
<header><h1>Наші фінанси</h1></header>
<section class="card"><form method="post">
<input type="hidden" name="csrf" value="{csrf_token()}">
{f'<p class="error" role="alert">{escape(error)}</p>' if error else ''}
<label class="field"><span>Логін</span><input name="login" autocomplete="username" autocapitalize="none" required></label>
<label class="field"><span>Пароль</span><input name="password" type="password" autocomplete="current-password" required></label>
<button class="btn wide" type="submit">Увійти</button>
</form></section>""")


@app.post("/logout")
def logout():
    check_csrf()
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
def index():
    flash = ""
    if "added" in session:
        flash = escape(session.pop("added"))
    return report.render(LEDGER, head=HEAD, nav=nav(), flash=flash, viewer=me(), settings_url=url_for("limits"))


def expense_accounts():
    """Відкриті рахунки витрат кожної людини, крім «Без-Категорії»: {людина: [рахунок]}."""
    entries, _, _ = loader.load_file(str(LEDGER))
    accounts = {p: [] for p in report.PEOPLE}
    for e in entries:
        if isinstance(e, data.Open) and e.account.startswith("Expenses:") and not e.account.endswith("Без-Категорії"):
            accounts[e.account.split(":")[1]].append(e.account)
    return accounts


@app.route("/add", methods=["GET", "POST"])
def add():
    accounts = expense_accounts()[me()]
    today = datetime.now(WARSAW).date()
    form = {"date": today.isoformat(), "amount": "", "account": "", "description": "", "shared": "ні"}
    error = ""
    if request.method == "POST":
        check_csrf()
        form.update({k: request.form.get(k, "").strip() for k in form})
        try:
            entry = parse_cash(form, accounts, today)
        except ValueError as e:
            error = str(e)
        else:
            try:
                cashbook.append(CASH, LEDGER, entry)
            except ValueError as e:
                error = str(e)
            else:
                kind = "спільна" if entry["shared"] else "особиста"
                session["added"] = f"Додано: {entry['description']}, {report.zl(entry['amount'])} ({kind})."
                return redirect(f"{url_for('index')}?p={entry['person']}&m={entry['date']:%Y-%m}")
    options = "".join(
        f'<option value="{a}"{" selected" if a == form["account"] else ""}>{report.category_name(a.rsplit(":", 1)[1])}</option>'
        for a in accounts
    )
    shared = "".join(
        f'<label><input type="radio" name="shared" value="{v}"{" checked" if v == form["shared"] else ""}><span>{label}</span></label>'
        for v, label in (("ні", "Особиста"), ("так", "Спільна"))
    )
    return page("Додати готівку", f"""
<header><h1>Готівка</h1><nav class="nav"><a class="btn ghost" href="{url_for('index')}">До звіту</a></nav></header>
<section class="card"><form method="post">
<input type="hidden" name="csrf" value="{csrf_token()}">
{f'<p class="error" role="alert">{escape(error)}</p>' if error else ''}
<label class="field"><span>Сума, зл</span><input name="amount" inputmode="decimal" placeholder="12,50" value="{escape(form['amount'])}" required autofocus></label>
<label class="field"><span>Що купили</span><input name="description" maxlength="80" placeholder="Кава на ринку" value="{escape(form['description'])}" required></label>
<label class="field"><span>Категорія</span><select name="account" required>{options}</select></label>
<label class="field"><span>Дата</span><input name="date" type="date" min="2026-08-01" max="{today + timedelta(days=1)}" value="{escape(form['date'])}" required></label>
<div class="field"><span>Хто бачить</span><div class="radios">{shared}</div></div>
<button class="btn wide" type="submit">Зберегти</button>
</form></section>
<p class="foot">Платить {me()}. Особисту витрату бачите лише ви, спільну — обоє.</p>""")


def money(text):
    """«1 234,50» -> Decimal("1234.50"); ValueError, якщо це не число."""
    try:
        value = Decimal(text.replace("\xa0", "").replace(" ", "").replace(",", ".")).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise ValueError("Сума має бути числом, наприклад 12,50.") from None
    return value


def parse_cash(form, accounts, today):
    """Перевіряє поля форми. Повертає запис або кидає ValueError з поясненням для людини."""
    amount = money(form["amount"])
    if not Decimal("0.01") <= amount <= Decimal("100000"):
        raise ValueError("Сума має бути від 0,01 до 100 000 зл.")
    if form["account"] not in accounts:
        raise ValueError("Оберіть категорію.")
    try:
        day = date.fromisoformat(form["date"])
    except ValueError:
        raise ValueError("Дата має бути у форматі РРРР-ММ-ДД.") from None
    if not date(2026, 8, 1) <= day <= today + timedelta(days=1):
        raise ValueError("Дата має бути між 1 серпня 2026 і сьогодні.")
    description = re.sub(r'[\s"\\]+', " ", form["description"]).strip()[:80]
    if not description:
        raise ValueError("Напишіть, що купили.")
    if form["shared"] not in ("так", "ні"):
        raise ValueError("Оберіть, хто бачить витрату.")
    return {"person": me(), "amount": amount, "account": form["account"], "date": day,
            "description": description, "user": session["user"], "shared": form["shared"] == "так"}


@app.route("/limits", methods=["GET", "POST"])
def limits():
    """Ліміти на місяць для своїх категорій. Чужі рядки limits.csv не показуємо і не змінюємо."""
    accounts = expense_accounts()[me()]
    current = report.load_limits()
    values = {a: f"{current[a]:f}".replace(".", ",") if a in current else "" for a in accounts}
    error = ""
    if request.method == "POST":
        check_csrf()
        values = {a: request.form.get(a, "").strip() for a in accounts}
        try:
            mine = {}
            for a, text in values.items():
                if text:
                    mine[a] = money(text)
                    if not Decimal("1") <= mine[a] <= Decimal("1000000"):
                        raise ValueError("Ліміт має бути від 1 до 1 000 000 зл або порожнім.")
        except ValueError as e:
            error = str(e)
        else:
            save_limits(mine)
            session["added"] = "Ліміти збережено."
            return redirect(url_for("index"))
    fields = "".join(
        f'<label class="field"><span>{report.category_name(a.rsplit(":", 1)[1])}</span>'
        f'<input name="{a}" inputmode="decimal" placeholder="без ліміту" value="{escape(values[a])}"></label>'
        for a in accounts
    )
    return page("Ліміти", f"""
<header><h1>Ліміти</h1><nav class="nav"><a class="btn ghost" href="{url_for('index')}">До звіту</a></nav></header>
<section class="card"><form method="post">
<input type="hidden" name="csrf" value="{csrf_token()}">
{f'<p class="error" role="alert">{escape(error)}</p>' if error else ''}
<p class="foot">Скільки {me()} готові витрачати на місяць, зл. Порожнє поле — без ліміту.</p>
{fields}
<button class="btn wide" type="submit">Зберегти</button>
</form></section>""")


def save_limits(mine):
    """Переписує свої рядки limits.csv, чужі лишає як були. Блокування — на випадок двох збережень одночасно."""
    with open(report.LIMITS, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        rows = {r["рахунок"]: r["ліміт"] for r in csv.DictReader(f) if report.owner(r["рахунок"]) != me()}
        rows.update({a: f"{v:f}" for a, v in mine.items()})
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(["рахунок", "ліміт"])
        writer.writerows(sorted(rows.items()))
        f.seek(0)
        f.truncate()
        f.write(out.getvalue())


# ----- Файли для встановлення на телефон (без даних, доступні без входу) -----
@app.get("/static/<path:name>")
def static_file(name):
    return send_from_directory(STATIC, name, max_age=86400)


@app.get("/manifest.webmanifest")
def manifest():
    return send_from_directory(STATIC, "manifest.webmanifest", mimetype="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    response = send_from_directory(STATIC, "sw.js", mimetype="text/javascript", max_age=0)
    response.headers["Service-Worker-Allowed"] = "/"
    return response


def https_only(wsgi):
    """Лише HTTPS: http-запит перенаправляємо на https, браузеру кажемо не ходити по http (HSTS)."""
    def middleware(environ, start_response):
        if not DEV and environ.get("wsgi.url_scheme") != "https":
            host = environ.get("HTTP_HOST", "")
            path = environ.get("PATH_INFO", "/")
            query = environ.get("QUERY_STRING", "")
            start_response("301 Moved Permanently", [("Location", f"https://{host}{path}" + (f"?{query}" if query else ""))])
            return [b""]

        def secure_headers(status, headers, exc_info=None):
            headers += [
                ("X-Content-Type-Options", "nosniff"),
                ("X-Frame-Options", "DENY"),
                ("Referrer-Policy", "same-origin"),
            ]
            if not DEV:
                headers.append(("Strict-Transport-Security", "max-age=31536000"))
            return start_response(status, headers, exc_info)

        return wsgi(environ, secure_headers)
    return middleware


# PythonAnywhere стоїть перед застосунком як проксі і передає справжню схему в X-Forwarded-Proto.
application = ProxyFix(https_only(app.wsgi_app), x_proto=1, x_for=1)
