"""Збирає звіт: виконує збережені запити з main.beancount і малює відповіді для Олі й Марка.

`uv run python report.py` пише report.html (без інтернету, відкривається в браузері).
Веб-застосунок (app.py) викликає render() на кожен запит, тож звіт завжди свіжий.
"""
import csv
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from html import escape
from pathlib import Path

import beanquery
from beancount import loader
from beancount.core import data

ROOT = Path(__file__).parent
LEDGER = ROOT / "main.beancount"
LIMITS = ROOT / "limits.csv"
PEOPLE = ["Оля", "Марко"]
VIEWS = ["Разом", *PEOPLE]
MONTH_NAMES = {1: "Січень", 2: "Лютий", 3: "Березень", 4: "Квітень", 5: "Травень", 6: "Червень",
               7: "Липень", 8: "Серпень", 9: "Вересень", 10: "Жовтень", 11: "Листопад", 12: "Грудень"}
MONTH_GEN = {1: "січня", 2: "лютого", 3: "березня", 4: "квітня", 5: "травня", 6: "червня",
             7: "липня", 8: "серпня", 9: "вересня", 10: "жовтня", 11: "листопада", 12: "грудня"}
CATEGORY_NAMES = {"Краса-Побут": "Краса і побут", "Доставка-Їжі": "Доставка їжі"}


def category_name(leaf):
    return CATEGORY_NAMES.get(leaf, leaf.replace("-", " ").capitalize())


def zl(x, decimals=2):
    return f"{x:,.{decimals}f}".replace(",", " ").replace(".", ",") + " зл"


def pct(a, b, decimals=0):
    return f"{a / b * 100:.{decimals}f}".replace(".", ",") + "%" if b else "—"


def owner(account):
    """Expenses:Оля:Кафе -> Оля."""
    parts = account.split(":")
    return parts[1] if len(parts) > 1 else None


def visible(entries, person):
    """Що бачить person: усі свої записи і лише спільні (#shared) записи іншої людини."""
    keep = []
    for e in entries:
        if isinstance(e, data.Transaction):
            if "shared" in e.tags or any(owner(p.account) == person for p in e.postings):
                keep.append(e)
        elif isinstance(e, data.Open) or not hasattr(e, "account") or owner(e.account) == person:
            keep.append(e)
    return keep


def load_limits(path=None):
    """limits.csv: рахунок,ліміт -> {рахунок: Decimal}. Порожній ліміт — ліміту немає."""
    path = path or LIMITS
    if not Path(path).exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return {r["рахунок"]: Decimal(r["ліміт"]) for r in csv.DictReader(f) if r["ліміт"].strip()}


def load(ledger=LEDGER, viewer=None):
    """Виконує збережені запити і повертає суми по (рік, місяць) і людині.
    viewer — хто дивиться: запити бачать лише visible(); None — усі дані (статичний report.html)."""
    entries, errors, options = loader.load_file(str(ledger))
    if errors:
        raise SystemExit(f"У main.beancount є помилки: {errors[0]}")
    queries = {e.name: e.query_string for e in entries if isinstance(e, data.Query)}
    if viewer:
        entries = visible(entries, viewer)
    connection = beanquery.connect("beancount:", entries=entries, errors=[], options=options)

    def run(name):
        cursor = connection.execute(queries[name])
        columns = [c.name for c in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    d = {
        "categories": defaultdict(lambda: defaultdict(Decimal)),  # (key, view) -> {категорія: сума}
        "savings": defaultdict(lambda: defaultdict(Decimal)),     # (key, view) -> income/spent/saved
        "fixed": defaultdict(lambda: defaultdict(Decimal)),       # (key, view) -> {True/False: сума}
        "variable": defaultdict(dict),                            # key -> {людина: змінні}
        "cash": defaultdict(list),                                # (key, view) -> [запис]
        "spent": defaultdict(dict),                               # key -> {рахунок: сума}
        "last_day": {},                                           # key -> остання дата в даних
    }
    for r in run("витрати-за-категоріями"):
        key = (r["year"], r["month"])
        for view in ("Разом", r["person"]):
            d["categories"][key, view][category_name(r["category"])] += r["total"]
        d["spent"][key][f"Expenses:{r['person']}:{r['category']}"] = r["total"]
    for r in run("норма-заощаджень"):
        key = (r["year"], r["month"])
        for view in ("Разом", r["person"]):
            for field in ("income", "spent", "saved"):
                d["savings"][key, view][field] += r[field]
        d["last_day"][key] = max(d["last_day"].get(key, r["last_day"]), r["last_day"])
    for r in run("фіксовані-і-змінні"):
        key = (r["year"], r["month"])
        for view in ("Разом", r["person"]):
            d["fixed"][key, view][bool(r["fixed"])] += r["total"]
        if not r["fixed"]:
            d["variable"][key][r["person"]] = r["total"]
    for r in run("готівка"):
        key = (r["date"].year, r["date"].month)
        for view in ("Разом", r["person"]):
            d["cash"][key, view].append(r)
    d["keys"] = sorted(d["last_day"])
    return d


def month_caption(d, key):
    last = d["last_day"][key]
    end = date(key[0] + key[1] // 12, key[1] % 12 + 1, 1).toordinal() - 1
    if last.toordinal() < end - 2:
        return f"неповний: дані до {last.day} {MONTH_GEN[last.month]}"
    return "місяць закінчено"


def block_categories(d, key, view):
    rows = sorted(d["categories"][key, view].items(), key=lambda kv: -kv[1])
    if not rows:
        return '<section class="card"><h2>Куди йдуть гроші</h2><p class="verdict">Витрат за цей місяць немає.</p></section>'
    total = sum(v for _, v in rows)
    top = rows[0][1] or Decimal(1)
    bars = "".join(
        f'<div class="row" title="{escape(n)}: {zl(v)}, {pct(v, total)} витрат">'
        f'<span class="name">{escape(n)}</span>'
        f'<span class="track"><span class="bar" style="width:{max(v, 0) / top * 100:.1f}%"></span></span>'
        f'<span class="val">{zl(v, 0)}</span></div>'
        for n, v in rows
    )
    table = "".join(
        f"<tr><td>{escape(n)}</td><td>{zl(v)}</td><td>{pct(v, total)}</td></tr>" for n, v in rows
    )
    verdict = f"Найбільша стаття — {rows[0][0].lower()}: {pct(rows[0][1], total)} усіх витрат."
    return f"""
<section class="card"><h2>Куди йдуть гроші</h2>
<div class="hero">{zl(total, 0)}</div><div class="sub">витрачено за місяць</div>
<div class="chart">{bars}</div>
<p class="verdict">{verdict}</p>
<details><summary>Показати таблицею</summary>
<table><tr><th>Категорія</th><th>Сума</th><th>Частка</th></tr>{table}</table></details></section>"""


def stacked(parts):
    """parts: [(підпис, значення, css-клас)] -> горизонтальна смуга + легенда."""
    total = sum(v for _, v, _ in parts)
    segs = "".join(
        f'<span class="seg {cls}" style="flex:{max(v, 0)}" title="{label}: {zl(v)}"></span>'
        for label, v, cls in parts
    )
    legend = "".join(
        f'<span class="key"><i class="sw {cls}"></i>{label} <b>{zl(v, 0)}</b> · {pct(v, total)}</span>'
        for label, v, cls in parts
    )
    return f'<div class="stack">{segs}</div><div class="legend">{legend}</div>'


def block_savings(d, key, view, partial, private=False):
    if private:
        return f'<section class="card"><h2>Скільки відкладено</h2><p class="verdict">Доходи й заощадження {view} бачить лише {view}.</p></section>'
    s = d["savings"][key, view]
    income, spent, saved = s["income"], s["spent"], s["saved"]
    if not income:
        return f"""
<section class="card"><h2>Скільки відкладено</h2>
<div class="hero">—</div><div class="sub">доходу за цей місяць у даних ще немає</div>
<p class="verdict">Витрачено {zl(spent, 0)}. Норму заощаджень порахуємо, коли надійде зарплата.</p></section>"""
    rate = pct(saved, income, 1)
    warn = " Місяць ще не закінчився, тому норма завищена." if partial else ""
    bar = stacked([("Відкладено", saved, "a"), ("Витрати", spent, "b")]) if saved > 0 else ""
    return f"""
<section class="card"><h2>Скільки відкладено</h2>
<div class="hero">{rate}</div><div class="sub">доходу відкладено ({zl(income, 0)} − {zl(spent, 0)})</div>
{bar}
<p class="verdict">Відкладено {zl(saved, 0)} із {zl(income, 0)}.{warn}</p></section>"""


def block_fixed(d, key, view):
    split = d["fixed"][key, view]
    fixed, managed = split.get(True, Decimal(0)), split.get(False, Decimal(0))
    total = fixed + managed
    by_person = ""
    if view == "Разом":
        rows = "".join(
            f"<tr><td>{p}</td><td>{zl(d['variable'][key].get(p, Decimal(0)))}</td></tr>" for p in PEOPLE
        )
        by_person = f'<table class="people"><tr><th>Змінні витрати</th><th>Сума</th></tr>{rows}</table>'
    return f"""
<section class="card"><h2>Фіксовані й змінні</h2>
<div class="hero">{pct(fixed, total)}</div><div class="sub">витрат — фіксовані ({zl(fixed, 0)})</div>
{stacked([("Змінні", managed, "a"), ("Фіксовані", fixed, "b")])}
<p class="verdict">Змінних витрат, якими можна керувати, — {zl(managed)}.</p>{by_person}</section>"""


def limit_rows(d, key, view, viewer, limits):
    """[(назва, витрачено, ліміт)] для рахунків цього перегляду. Ліміти бачить лише їхній власник."""
    owners = PEOPLE if view == "Разом" else [view]
    rows = []
    for account, limit in limits.items():
        who = owner(account)
        if who in owners and viewer in (None, who):
            name = category_name(account.rsplit(":", 1)[1]) + (f" · {who}" if view == "Разом" and not viewer else "")
            rows.append((name, d["spent"][key].get(account, Decimal(0)), limit))
    return sorted(rows, key=lambda r: -(r[1] / r[2] if r[2] else 0))


def level(spent, limit):
    """Зелений до 80%, жовтий 80–100%, червоний понад ліміт."""
    if spent > limit:
        return "over", f"перевищено на {zl(spent - limit, 0)}"
    if spent >= limit * Decimal("0.8"):
        return "near", f"{pct(spent, limit)} ліміту"
    return "fine", f"{pct(spent, limit)} ліміту"


def limits_banner(rows):
    hot = [f"{escape(n)}: {level(s, l)[1]}" for n, s, l in rows if level(s, l)[0] != "fine"]
    return f'<p class="alert" role="alert"><b>Увага, ліміти.</b> {" · ".join(hot)}</p>' if hot else ""


def block_limits(rows, view, viewer, settings_url):
    if viewer and view not in ("Разом", viewer):
        return f'<section class="card"><h2>Ліміти</h2><p class="verdict">Ліміти {view} бачить лише {view}.</p></section>'
    link = f' <a href="{settings_url}">Налаштувати ліміти</a>' if settings_url else ""
    if not rows:
        return f'<section class="card"><h2>Ліміти</h2><p class="verdict">Лімітів ще немає.{link}</p></section>'
    items = "".join(
        f'<div class="limit {level(s, l)[0]}"><div class="lhead"><span>{escape(n)}</span>'
        f'<span>{zl(s, 0)} з {zl(l, 0)}</span></div>'
        f'<span class="ltrack"><span class="lbar" style="width:{min(s / l * 100, 100) if l else 100:.1f}%"></span></span>'
        f'<small>{level(s, l)[1]}</small></div>'
        for n, s, l in rows
    )
    return f'<section class="card"><h2>Ліміти на місяць</h2>{items}<p class="foot">{link}</p></section>'


def block_cash(d, key, view):
    rows = d["cash"][key, view]
    if not rows:
        return ""
    items = "".join(
        f"<tr><td>{r['date'].day} {MONTH_GEN[r['date'].month]}</td><td>{escape(r['person'])}</td>"
        f"<td>{escape(r['narration'])}<br><small>{escape(category_name(r['category']))}</small></td>"
        f"<td>{zl(r['number'])}</td></tr>"
        for r in rows
    )
    return f"""
<section class="card"><h2>Готівка, додана з телефону</h2>
<table class="cash">{items}</table></section>"""


CSS = """
/* Розкладка — Boro UI зі Stitch; кольори — палітра логотипа Trajet (крижана гора). Усі кольори лише тут. */
:root {
  --bg:#e9eff3; --surface:#fff; --border:#d0dced; --text:#1e3550;
  --text-muted:#4f6277; /* у палітрі #53677D; на 2% темніше, щоб на тлі полів (--border) був контраст 4.5:1 */
  --accent:#739bbf; --accent-strong:#2b4c70; --on-accent:#fff;
  --positive:#2f7a59; --negative:#c2534b; --warning:#946a1e;
  --warning-soft:color-mix(in srgb, var(--warning) 12%, var(--surface)); --negative-soft:color-mix(in srgb, var(--negative) 12%, var(--surface));
  --cat1:#1e3550; --cat2:#739bbf; --cat3:#a9c1da; --cat4:#4a6f94; --cat5:#d0dced; --cat6:#2b4c70; --cat7:#8fb0cf; --cat8:#53677d;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:16px/1.5 Inter, -apple-system, BlinkMacSystemFont, system-ui, sans-serif; -webkit-font-smoothing:antialiased; }
main { max-width:720px; margin:0 auto; padding:0 24px calc(112px + env(safe-area-inset-bottom, 0px)); padding-top:env(safe-area-inset-top, 0); }
header { display:flex; align-items:center; gap:12px; margin:0 -24px; padding:14px 24px; border-bottom:1px solid var(--border); }
h1 { margin:0; flex:1; font-size:1.25rem; font-weight:600; letter-spacing:-.01em; }
.nav { display:flex; gap:8px; align-items:center; }
.btn { font:inherit; font-size:1rem; font-weight:600; border:0; border-radius:999px; padding:10px 20px; min-height:44px; display:inline-flex; align-items:center; justify-content:center; background:var(--accent-strong); color:var(--on-accent); text-decoration:none; cursor:pointer; }
.btn.ghost { background:var(--border); color:var(--text); }
.btn:active, .tabs button:active, .fab:active { transform:scale(.98); }
.sticky { position:sticky; top:0; z-index:1; background:var(--bg); padding:12px 0 4px; }
.tabs { display:flex; }
#people { background:var(--border); border-radius:999px; padding:4px; }
#people button { flex:1; min-height:44px; font:inherit; font-size:.95rem; color:var(--text); background:none; border:0; border-radius:999px; cursor:pointer; }
#people button[aria-selected="true"] { background:var(--accent-strong); color:var(--on-accent); font-weight:600; }
#months { justify-content:center; gap:4px; margin-top:4px; }
#months button { min-height:44px; padding:0 12px; font:inherit; font-size:.95rem; font-weight:500; color:var(--text-muted); background:none; border:0; border-bottom:2px solid transparent; cursor:pointer; }
#months button[aria-selected="true"] { color:var(--text); font-weight:600; border-bottom-color:var(--accent); }
.caption { color:var(--text-muted); margin:20px 0 8px; font-size:.75rem; font-weight:600; letter-spacing:.05em; text-transform:uppercase; }
.caption.partial { background:var(--warning-soft); border-radius:999px; padding:8px 14px; color:var(--text); }
.flash { position:fixed; z-index:2; left:24px; right:24px; bottom:calc(96px + env(safe-area-inset-bottom, 0px)); max-width:672px; margin:0 auto; background:var(--accent-strong); color:var(--on-accent); border-radius:999px; padding:14px 20px; animation:toast 5s forwards; }
@keyframes toast { 0%, 85% { opacity:1; } 100% { opacity:0; visibility:hidden; } }
.alert { background:var(--warning-soft); border:1px solid color-mix(in srgb, var(--warning) 35%, var(--surface)); border-radius:24px; padding:14px 18px; margin:16px 0 0; }
.tabbar { position:fixed; z-index:1; left:0; right:0; bottom:0; display:flex; justify-content:center; padding:6px 8px env(safe-area-inset-bottom, 0px); background:var(--surface); border:1px solid var(--border); border-bottom:0; border-radius:28px 28px 0 0; }
.tabbar button { flex:1; max-width:180px; min-height:56px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:2px; font:inherit; font-size:.7rem; color:var(--text-muted); background:none; border:0; cursor:pointer; }
.tabbar button[aria-selected="true"] { color:var(--accent-strong); font-weight:600; } .tabbar button[aria-selected="true"] svg { stroke:var(--accent); }
.tabbar svg { width:26px; height:26px; fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }
.fab { position:fixed; z-index:1; right:max(24px, calc(50% - 336px)); bottom:calc(84px + env(safe-area-inset-bottom, 0px)); width:60px; height:60px; border-radius:50%; display:flex; align-items:center; justify-content:center; background:var(--accent-strong); color:var(--on-accent); font-size:2rem; font-weight:300; text-decoration:none; }
.menu { position:relative; } .menu summary::-webkit-details-marker { display:none; }
.menu summary { list-style:none; display:flex; align-items:center; min-height:44px; padding:0 16px; border:1.5px solid var(--text); border-radius:999px; font-weight:600; cursor:pointer; }
.menu-list { position:absolute; right:0; top:calc(100% + 8px); z-index:3; min-width:210px; display:flex; flex-direction:column; padding:6px; background:var(--surface); border:1px solid var(--border); border-radius:24px; }
.menu-list a, .menu-list button { display:flex; align-items:center; width:100%; min-height:48px; padding:0 16px; border:0; border-radius:18px; background:none; color:var(--text); font:inherit; text-align:left; text-decoration:none; cursor:pointer; }
.menu-list a:hover, .menu-list button:hover { background:var(--border); } .menu-list form { margin:0; }
.card { background:var(--surface); border:1px solid var(--border); border-radius:24px; padding:24px; margin:16px 0; }
h2 { margin:0 0 12px; font-size:.75rem; color:var(--text-muted); font-weight:600; letter-spacing:.05em; text-transform:uppercase; }
.hero { font-size:3.5rem; line-height:1.1; font-weight:600; letter-spacing:-.03em; } .sub { color:var(--text-muted); margin:4px 0 20px; }
.row { display:grid; grid-template-columns:minmax(90px, 132px) 1fr 76px; align-items:center; gap:10px; margin:8px 0; }
.name { color:var(--text-muted); font-size:.9rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; } .val { text-align:right; font-size:.9rem; font-weight:500; white-space:nowrap; }
.track { height:14px; } .bar { display:block; height:100%; background:var(--accent); border-radius:0 4px 4px 0; }
.row:nth-child(8n+1) .bar { background:var(--cat1); } .row:nth-child(8n+2) .bar { background:var(--cat2); } .row:nth-child(8n+3) .bar { background:var(--cat3); } .row:nth-child(8n+4) .bar { background:var(--cat4); } .row:nth-child(8n+5) .bar { background:var(--cat5); } .row:nth-child(8n+6) .bar { background:var(--cat6); } .row:nth-child(8n+7) .bar { background:var(--cat7); } .row:nth-child(8n+0) .bar { background:var(--cat8); }
.row:nth-child(n+9) .bar { opacity:.6; } /* понад 8 категорій — ті самі кольори, але прозоріші */
.stack { display:flex; gap:2px; height:14px; }
.seg { min-width:2px; } .seg:first-child { border-radius:7px 0 0 7px; } .seg:last-child { border-radius:0 7px 7px 0; }
.a { background:var(--cat1); } .b { background:var(--cat2); }
.legend { display:flex; gap:16px; flex-wrap:wrap; margin-top:12px; font-size:.9rem; color:var(--text-muted); }
.sw { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; } .legend b { color:var(--text); font-weight:600; }
.limit { padding:14px 0; border-bottom:1px solid var(--border); } .limit:last-of-type { border-bottom:0; }
.lhead { display:flex; justify-content:space-between; gap:8px; } .lhead span:last-child { font-weight:600; white-space:nowrap; }
.ltrack { display:block; height:8px; background:var(--border); border-radius:4px; margin:8px 0 4px; overflow:hidden; }
.lbar { display:block; height:100%; border-radius:4px; } .fine .lbar { background:var(--positive); } .near .lbar { background:var(--warning); } .over .lbar { background:var(--negative); }
.over small { color:var(--negative); font-weight:600; }
.verdict { margin:16px 0 0; }
a { color:var(--accent-strong); }
details { margin-top:12px; color:var(--text-muted); } summary { cursor:pointer; padding:10px 0; }
table { width:100%; border-collapse:collapse; margin-top:8px; } td, th { padding:12px 6px; border-bottom:1px solid var(--border); text-align:left; vertical-align:top; }
th { font-size:.75rem; font-weight:600; letter-spacing:.05em; text-transform:uppercase; color:var(--text-muted); }
td:last-child, th:last-child { text-align:right; white-space:nowrap; }
small { color:var(--text-muted); }
.month[hidden] { display:none; }
.foot { color:var(--text-muted); font-size:.85rem; }
"""


# Нижнє меню звіту: (ключ, підпис, іконка SVG).
SECTIONS = [
    ("spend", "Витрати", '<circle cx="12" cy="12" r="9"/><path d="M12 3v9h9"/>'),
    ("save", "Відкладено", '<path d="M12 3v12M7 10l5 5 5-5M4 20h16"/>'),
    ("fixed", "Фіксовані", '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>'),
    ("limits", "Ліміти", '<path d="M4 18a8 8 0 1 1 16 0"/><path d="M12 18l4-6"/>'),
]


def render(ledger=LEDGER, *, head="", nav="", flash="", viewer=None, limits=None, settings_url=""):
    """Повна HTML-сторінка звіту. head/nav/flash/viewer/settings_url — додатки від веб-застосунку."""
    d = load(ledger, viewer)
    limit_table = load_limits(limits)
    other = next(p for p in PEOPLE if p != viewer) if viewer else None
    scope = {"Разом": f"ваші витрати і спільні витрати {other}", other: "лише спільні витрати"} if viewer else {}
    keys = d["keys"]
    default = next((k for k in reversed(keys) if "закінчено" in month_caption(d, k)), keys[-1])
    month_id = lambda k: f"{k[0]}-{k[1]:02d}"
    view_tabs = "".join(
        f'<button role="tab" data-p="{v}" aria-selected="{str(v == "Разом").lower()}">{v}</button>' for v in VIEWS
    )
    month_tabs, panels = [], []
    for k in keys:
        cap = month_caption(d, k)
        partial = "неповний" in cap
        month_tabs.append(
            f'<button role="tab" data-m="{month_id(k)}" aria-selected="{str(k == default).lower()}">'
            f'{MONTH_NAMES[k[1]]}{" *" if partial else ""}</button>'
        )
        for v in VIEWS:
            rows = limit_rows(d, k, v, viewer, limit_table)
            note = f" · {scope[v]}" if v in scope else ""
            panels.append(
                f'<div class="month" data-m="{month_id(k)}" data-p="{v}" hidden>{limits_banner(rows)}'
                f'<p class="caption{" partial" if partial else ""}">{v} · {MONTH_NAMES[k[1]]} {k[0]} · {cap}{note}</p>'
                f'<div data-s="spend">{block_categories(d, k, v)}{block_cash(d, k, v)}</div>'
                f'<div data-s="save" hidden>{block_savings(d, k, v, partial, v == other)}</div>'
                f'<div data-s="fixed" hidden>{block_fixed(d, k, v)}</div>'
                f'<div data-s="limits" hidden>{block_limits(rows, v, viewer, settings_url)}</div></div>'
            )
    flash_html = f'<p class="flash" role="status">{flash}</p>' if flash else ""
    return f"""<!doctype html>
<html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Наші фінанси</title>{head}
<style>{CSS}</style></head><body><main>
<header><h1>Наші фінанси</h1>{nav}</header>
{flash_html}
<div class="sticky"><div class="tabs" role="tablist" id="people">{view_tabs}</div>
<div class="tabs" role="tablist" id="months">{''.join(month_tabs)}</div></div>
{''.join(panels)}
<p class="foot">* місяць ще не закінчився. Дані: виписки Олі й Марка за 1 серпня — 15 жовтня 2026 і готівка, додана з телефону; злоті.</p>
</main>
<nav class="tabbar" role="tablist" id="sections">{"".join(
    f'<button role="tab" data-s="{k}" aria-selected="{str(k == "spend").lower()}"><svg viewBox="0 0 24 24" aria-hidden="true">{icon}</svg>{label}</button>'
    for k, label, icon in SECTIONS)}</nav>
<script>
const pt = document.querySelectorAll('#people button'), mt = document.querySelectorAll('#months button'), panels = document.querySelectorAll('.month');
const st = document.querySelectorAll('#sections button');
let p = 'Разом', m = {json.dumps(month_id(default))}, s = 'spend';
function show() {{
  st.forEach(t => t.setAttribute('aria-selected', t.dataset.s === s));
  document.querySelectorAll('.month [data-s]').forEach(x => x.hidden = x.dataset.s !== s);
  pt.forEach(t => t.setAttribute('aria-selected', t.dataset.p === p));
  mt.forEach(t => t.setAttribute('aria-selected', t.dataset.m === m));
  panels.forEach(x => x.hidden = x.dataset.p !== p || x.dataset.m !== m);
  try {{ localStorage.setItem('view', JSON.stringify({{p, m}})); }} catch (e) {{}}
}}
pt.forEach(t => t.addEventListener('click', () => {{ p = t.dataset.p; show(); }}));
st.forEach(t => t.addEventListener('click', () => {{ s = t.dataset.s; show(); scrollTo(0, 0); }}));
// Меню в шапці закривається дотиком будь-де поза ним.
document.addEventListener('click', e => document.querySelectorAll('details.menu[open]').forEach(x => x.contains(e.target) || x.removeAttribute('open')));
mt.forEach(t => t.addEventListener('click', () => {{ m = t.dataset.m; show(); }}));
const has = (list, key, v) => [...list].some(t => t.dataset[key] === v);
try {{ const s = JSON.parse(localStorage.getItem('view') || '{{}}'); if (has(pt, 'p', s.p)) p = s.p; if (has(mt, 'm', s.m)) m = s.m; }} catch (e) {{}}
const q = new URLSearchParams(location.search);
if (has(pt, 'p', q.get('p'))) p = q.get('p');
if (has(mt, 'm', q.get('m'))) m = q.get('m');
show();
</script>
</body></html>"""


if __name__ == "__main__":
    (ROOT / "report.html").write_text(render(), encoding="utf-8")
    print("Записано report.html")
