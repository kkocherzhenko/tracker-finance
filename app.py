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
<meta name="theme-color" content="#e9eff3">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Фінанси">
<script>if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js');</script>"""


def page(title, body):
    return f"""<!doctype html>
<html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>{HEAD}
<style>{report.CSS}
form .field {{ display:block; margin:0 0 20px; }} form .field > span {{ display:block; color:var(--text-muted); font-size:.75rem; font-weight:600; letter-spacing:.05em; text-transform:uppercase; margin-bottom:6px; }}
input, select {{ font:inherit; font-size:1.05rem; width:100%; min-height:52px; padding:12px 18px; border-radius:16px; border:1px solid transparent; background:var(--border); color:var(--text); }}
input:focus, select:focus {{ outline:2px solid var(--accent); outline-offset:1px; border-color:var(--accent-strong); background:var(--surface); }}
input::placeholder {{ color:var(--text-muted); opacity:1; }}
select {{ -webkit-appearance:none; appearance:none; padding-right:44px; background:var(--border) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' fill='none' stroke='%234f6277' stroke-width='1.8' stroke-linecap='round'%3E%3Cpath d='M1 1.5l5 5 5-5'/%3E%3C/svg%3E") no-repeat right 18px center; }} /* стрілка: колір --text-muted, у data-URI змінні не працюють */
input[name=amount] {{ font-size:3rem; font-weight:500; letter-spacing:-.04em; padding:8px 18px; }}
.sr {{ position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap; }}
.amount {{ display:flex; align-items:baseline; gap:8px; margin:4px 0 24px; font-size:2.75rem; }}
.amount input[name=amount] {{ flex:1 1 0; min-width:0; min-height:0; padding:0; border:0; background:none; font-size:inherit; font-weight:600; letter-spacing:-.03em; text-align:right; }}
.amount .cur {{ flex:1 1 0; margin:0; font-size:.5em; }}
fieldset.field {{ border:0; padding:0; margin:0 0 20px; min-width:0; }}
fieldset.field > legend {{ padding:0; margin-bottom:6px; color:var(--text-muted); font-size:.75rem; font-weight:600; letter-spacing:.05em; text-transform:uppercase; }}
fieldset .radios + input {{ margin-top:8px; }}
.cats {{ display:grid; grid-template-columns:repeat(3, 1fr); gap:8px; }}
.cat {{ position:relative; }} .cat input {{ position:absolute; inset:0; width:100%; height:100%; min-height:0; margin:0; opacity:0; }}
.cat span {{ display:flex; flex-direction:column; align-items:center; justify-content:center; gap:6px; min-height:76px; padding:10px 4px; border:1.5px solid transparent; border-radius:16px; background:color-mix(in srgb, var(--border) 50%, var(--surface)); font-size:.8rem; line-height:1.2; text-align:center; cursor:pointer; }}
.cat svg {{ width:24px; height:24px; fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }}
.cat input:checked + span {{ border-color:var(--accent-strong); background:var(--surface); font-weight:600; }}
.cat span:active, .radios span:active {{ transform:scale(.98); }}
.cat input:focus-visible + span {{ outline:2px solid var(--accent); outline-offset:2px; }}
.savebar {{ position:sticky; bottom:0; margin:0 -24px; padding:12px 24px calc(12px + env(safe-area-inset-bottom, 0px)); background:linear-gradient(to bottom, transparent, var(--bg) 35%); }}
.radios {{ display:flex; gap:4px; padding:4px; background:var(--border); border-radius:999px; }} .radios label {{ flex:1; }} .radios label {{ position:relative; }} .radios input {{ position:absolute; inset:0; width:100%; height:100%; margin:0; opacity:0; }}
.radios span {{ display:block; text-align:center; padding:10px 6px; min-height:44px; border-radius:999px; white-space:nowrap; cursor:pointer; }}
.radios input:checked + span {{ background:var(--accent-strong); color:var(--on-accent); font-weight:600; }}
.radios input:focus-visible + span {{ outline:2px solid var(--accent); outline-offset:2px; }}
.lrow {{ display:flex; justify-content:space-between; align-items:center; gap:12px; min-height:56px; border-bottom:1px solid var(--border); color:var(--text); text-decoration:none; }}
.lrow:last-child {{ border-bottom:0; }} .lrow b {{ font-weight:600; }} .lrow b::after {{ content:"›"; color:var(--text-muted); font-weight:400; margin-left:12px; }}
.stackbtn {{ display:flex; flex-direction:column; gap:8px; }}
.btn.wide {{ width:100%; min-height:56px; font-size:1.05rem; }}
.error {{ display:flex; gap:8px; align-items:flex-start; margin:0 0 16px; color:var(--negative); font-weight:500; }}
.error svg {{ flex:none; width:22px; height:22px; fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; }}
body:has(.login) {{ background:linear-gradient(to bottom, var(--bg), color-mix(in srgb, var(--accent) 15%, var(--bg))) fixed; }}
main:has(.login) {{ padding-bottom:24px; }}
.login {{ min-height:calc(100dvh - 24px); max-width:420px; margin:0 auto; display:flex; flex-direction:column; align-items:center; justify-content:center; }}
.login img {{ border-radius:16px; }} .login h1 {{ flex:none; margin:12px 0 4px; text-align:center; }} .login .card {{ width:100%; }}
</style></head><body><main>{body}</main></body></html>"""


def error_html(error):
    """Помилка форми: іконка і текст кольору --negative на білому (контраст 4.5:1)."""
    if not error:
        return ""
    return ('<p class="error" role="alert"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/>'
            f'<path d="M12 7.5v5.5M12 16.5h.01"/></svg>{escape(error)}</p>')


def nav():
    return f"""<a class="fab" href="{url_for('add')}" aria-label="Додати готівку">+</a>
<details class="menu"><summary aria-label="Меню: {me()}">{me()}</summary>
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
<div class="login"><img src="/static/icon-192.png" alt="" width="64" height="64"><h1>Наші фінанси</h1>
<section class="card"><form method="post">
<input type="hidden" name="csrf" value="{csrf_token()}">
{error_html(error)}
<label class="field"><span>Логін</span><input name="login" autocomplete="username" autocapitalize="none" required></label>
<label class="field"><span>Пароль</span><input name="password" type="password" autocomplete="current-password" required></label>
<button class="btn wide" type="submit">Увійти</button>
</form></section></div>""")


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
    cats = "".join(
        f'<label class="cat"><input type="radio" name="account" value="{a}" required{" checked" if a == form["account"] else ""}>'
        f'<span>{report.icon(report.category_name(a.rsplit(":", 1)[1]))}{report.category_name(a.rsplit(":", 1)[1])}</span></label>'
        for a in accounts
    )
    yesterday = (today - timedelta(days=1)).isoformat()
    when = {today.isoformat(): "today", yesterday: "yesterday"}.get(form["date"], "other")
    dates = "".join(
        f'<label><input type="radio" name="when" value="{v}"{" checked" if v == when else ""}><span>{label}</span></label>'
        for v, label in (("today", "Сьогодні"), ("yesterday", "Вчора"), ("other", "Інша дата"))
    )
    shared = "".join(
        f'<label><input type="radio" name="shared" value="{v}"{" checked" if v == form["shared"] else ""}><span>{label}</span></label>'
        for v, label in (("ні", "Особиста"), ("так", "Спільна"))
    )
    return page("Додати готівку", f"""
<header><h1>Готівка</h1><nav class="nav"><a class="btn ghost" href="{url_for('index')}">До звіту</a></nav></header>
<form method="post" class="pay">
<input type="hidden" name="csrf" value="{csrf_token()}">
<section class="card">
{error_html(error)}
<label class="amount"><span class="sr">Сума, зл</span><input name="amount" inputmode="decimal" placeholder="0" value="{escape(form['amount'])}" required autofocus><span class="cur" aria-hidden="true">зл</span></label>
<label class="field"><span>Що купили</span><input name="description" maxlength="80" placeholder="Кава на ринку" value="{escape(form['description'])}" required></label>
<fieldset class="field"><legend>Категорія</legend><div class="cats">{cats}</div></fieldset>
<fieldset class="field"><legend>Дата</legend><div class="radios">{dates}</div>
<input name="date" type="date" min="2026-08-01" max="{today + timedelta(days=1)}" value="{escape(form['date'])}" required aria-label="Дата"></fieldset>
<div class="field"><span>Хто бачить</span><div class="radios">{shared}</div></div>
</section>
<div class="savebar"><button class="btn wide" type="submit">Зберегти</button></div>
</form>
<script>
// «Сьогодні» / «Вчора» ставлять дату самі; поле дати видно лише для «Інша дата». Без JS поле видно завжди.
const f = document.querySelector('form.pay');
function syncDate() {{
  const w = f.when.value;
  if (w === 'today') f.date.value = '{today.isoformat()}';
  if (w === 'yesterday') f.date.value = '{yesterday}';
  f.date.hidden = w !== 'other';
}}
f.querySelectorAll('[name=when]').forEach(r => r.addEventListener('change', syncDate));
syncDate();
</script>
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
    """Ліміти на місяць: обираємо одну свою категорію і ставимо їй ліміт. Чужі рядки limits.csv не показуємо і не змінюємо."""
    accounts = expense_accounts()[me()]
    name = lambda a: report.category_name(a.rsplit(":", 1)[1])
    current = report.load_limits()
    mine = {a: current[a] for a in accounts if a in current}
    chosen = request.values.get("account", "")
    error = ""
    if request.method == "POST":
        check_csrf()
        amount = request.form.get("amount", "").strip()
        try:
            if chosen not in accounts:
                raise ValueError("Оберіть категорію.")
            if request.form.get("remove"):
                mine.pop(chosen, None)
                done = f"{name(chosen)}: ліміт прибрано."
            else:
                mine[chosen] = money(amount)
                if not Decimal("1") <= mine[chosen] <= Decimal("1000000"):
                    raise ValueError("Ліміт має бути від 1 до 1 000 000 зл.")
                done = f"{name(chosen)}: ліміт {report.zl(mine[chosen], 0)} на місяць."
        except ValueError as e:
            error = str(e)
        else:
            save_limits(mine)
            session["added"] = done
            return redirect(url_for("limits", account=chosen))
    if chosen not in accounts:
        chosen = accounts[0]
    if request.method == "GET":
        amount = f"{mine[chosen]:f}".replace(".", ",") if chosen in mine else ""
    flash = escape(session.pop("added", ""))
    options = "".join(
        f'<option value="{a}"{" selected" if a == chosen else ""}>{name(a)}{f" — {report.zl(mine[a], 0)}" if a in mine else ""}</option>'
        for a in accounts
    )
    rows = "".join(
        f'<a class="lrow" href="{url_for("limits", account=a)}"><span>{name(a)}</span><b>{report.zl(v, 0)}</b></a>'
        for a, v in mine.items()
    ) or '<p class="foot">Лімітів ще немає. Оберіть категорію вище.</p>'
    remove = '<button class="btn ghost wide" type="submit" name="remove" value="1" formnovalidate>Прибрати ліміт</button>' if chosen in mine else ""
    return page("Ліміти", f"""
<header><h1>Ліміти</h1><nav class="nav"><a class="btn ghost" href="{url_for('index')}">До звіту</a></nav></header>
{f'<p class="flash" role="status">{flash}</p>' if flash else ''}
<section class="card"><h2>Задати ліміт</h2><form method="post">
<input type="hidden" name="csrf" value="{csrf_token()}">
{error_html(error)}
<label class="field"><span>Категорія</span><select name="account" onchange="location.href='?account='+encodeURIComponent(this.value)">{options}</select></label>
<label class="field"><span>Ліміт на місяць, зл</span><input name="amount" inputmode="decimal" placeholder="500" value="{escape(amount)}" required></label>
<div class="stackbtn"><button class="btn wide" type="submit">Зберегти</button>{remove}</div>
</form></section>
<section class="card"><h2>Встановлені ліміти · {me()}</h2>{rows}</section>""")


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
