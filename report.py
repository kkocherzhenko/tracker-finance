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
        return '<section class="card"><h2>1. Куди йдуть гроші</h2><p class="verdict">Витрат за цей місяць немає.</p></section>'
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
<section class="card"><h2>1. Куди йдуть гроші</h2>
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
        return f'<section class="card"><h2>2. Скільки відкладено</h2><p class="verdict">Доходи й заощадження {view} бачить лише {view}.</p></section>'
    s = d["savings"][key, view]
    income, spent, saved = s["income"], s["spent"], s["saved"]
    if not income:
        return f"""
<section class="card"><h2>2. Скільки відкладено</h2>
<div class="hero">—</div><div class="sub">доходу за цей місяць у даних ще немає</div>
<p class="verdict">Витрачено {zl(spent, 0)}. Норму заощаджень порахуємо, коли надійде зарплата.</p></section>"""
    rate = pct(saved, income, 1)
    warn = " Місяць ще не закінчився, тому норма завищена." if partial else ""
    bar = stacked([("Відкладено", saved, "a"), ("Витрати", spent, "b")]) if saved > 0 else ""
    return f"""
<section class="card"><h2>2. Скільки відкладено</h2>
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
<section class="card"><h2>3. Фіксовані й змінні</h2>
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
        return f'<section class="card"><h2>4. Ліміти</h2><p class="verdict">Ліміти {view} бачить лише {view}.</p></section>'
    link = f' <a href="{settings_url}">Налаштувати ліміти</a>' if settings_url else ""
    if not rows:
        return f'<section class="card"><h2>4. Ліміти</h2><p class="verdict">Лімітів ще немає.{link}</p></section>'
    items = "".join(
        f'<div class="limit {level(s, l)[0]}"><div class="lhead"><span>{escape(n)}</span>'
        f'<span>{zl(s, 0)} з {zl(l, 0)}</span></div>'
        f'<span class="ltrack"><span class="lbar" style="width:{min(s / l * 100, 100) if l else 100:.1f}%"></span></span>'
        f'<small>{level(s, l)[1]}</small></div>'
        for n, s, l in rows
    )
    return f'<section class="card"><h2>4. Ліміти на місяць</h2>{items}<p class="foot">{link}</p></section>'


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
:root { --surface:#f5f5f7; --card:#fff; --ink:#1d1d1f; --ink2:#6e6e73; --line:#e5e5ea; --accent:#0071e3; --muted:#c7c7cc; --warn:#fff4d6; --ok:#e3f5e1; --seg:#e3e3e8; --glass:rgba(245,245,247,.8); --fine:#34c759; --near:#ff9f0a; --over:#ff3b30; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --surface:#000; --card:#1c1c1e; --ink:#f5f5f7; --ink2:#98989d; --line:#2c2c2e; --accent:#0a84ff; --muted:#48484a; --warn:#3a2f0b; --ok:#14331a; --seg:#2c2c2e; --glass:rgba(0,0,0,.75); } }
:root[data-theme="dark"] { --surface:#000; --card:#1c1c1e; --ink:#f5f5f7; --ink2:#98989d; --line:#2c2c2e; --accent:#0a84ff; --muted:#48484a; --warn:#3a2f0b; --ok:#14331a; --seg:#2c2c2e; --glass:rgba(0,0,0,.75); }
* { box-sizing:border-box; }
body { margin:0; background:var(--surface); color:var(--ink); font:16px/1.5 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", system-ui, sans-serif; -webkit-font-smoothing:antialiased; }
main { max-width:720px; margin:0 auto; padding:0 16px 48px; padding-top:env(safe-area-inset-top, 0); }
header { padding:24px 0 8px; display:flex; align-items:center; gap:12px; flex-wrap:wrap; } h1 { margin:0; font-size:2.1rem; font-weight:700; letter-spacing:-.02em; flex:1; }
.nav { display:flex; gap:8px; align-items:center; }
.btn { font:inherit; font-size:.95rem; border:0; border-radius:999px; padding:8px 16px; min-height:44px; display:inline-flex; align-items:center; justify-content:center; background:var(--accent); color:#fff; text-decoration:none; cursor:pointer; font-weight:600; }
.btn.ghost { background:var(--seg); color:var(--ink); font-weight:400; }
.tabs { display:flex; gap:2px; padding:4px 0; }
.sticky { position:sticky; top:0; z-index:1; background:var(--glass); backdrop-filter:saturate(180%) blur(20px); -webkit-backdrop-filter:saturate(180%) blur(20px); padding:4px 0; }
.tabs button:first-child { border-radius:9px 0 0 9px; } .tabs button:last-child { border-radius:0 9px 9px 0; }
.tabs button { flex:1; font:inherit; font-size:.9rem; color:var(--ink); background:var(--seg); border:0; border-radius:0; padding:7px 8px; min-height:44px; cursor:pointer; }
.tabs button[aria-selected="true"] { background:var(--accent); color:#fff; font-weight:600; }
.caption { color:var(--ink2); margin:12px 0; } .caption.partial { background:var(--warn); border-radius:12px; padding:8px 14px; color:var(--ink); }
.flash { position:fixed; z-index:2; left:16px; right:16px; bottom:calc(16px + env(safe-area-inset-bottom, 0px)); max-width:688px; margin:0 auto; background:var(--ink); color:var(--card); border-radius:14px; padding:12px 16px; box-shadow:0 4px 16px rgba(0,0,0,.2); animation:toast 5s forwards; }
@keyframes toast { 0%, 85% { opacity:1; } 100% { opacity:0; visibility:hidden; } }
.alert { background:var(--warn); border-radius:12px; padding:10px 14px; margin:12px 0; }
.user { color:var(--ink2); font-size:.95rem; }
.limit { margin:12px 0; } .lhead { display:flex; justify-content:space-between; gap:8px; font-size:.95rem; }
.ltrack { display:block; height:10px; background:var(--seg); border-radius:5px; margin:4px 0 2px; overflow:hidden; }
.lbar { display:block; height:100%; border-radius:5px; } .fine .lbar { background:var(--fine); } .near .lbar { background:var(--near); } .over .lbar { background:var(--over); }
.over small { color:var(--over); font-weight:600; }
summary { padding:10px 0; }
.card { background:var(--card); border-radius:20px; padding:24px; margin:16px 0; box-shadow:0 1px 2px rgba(0,0,0,.04), 0 4px 16px rgba(0,0,0,.04); }
h2 { margin:0 0 8px; font-size:.95rem; color:var(--ink2); font-weight:600; }
.hero { font-size:3.25rem; line-height:1.1; font-weight:700; letter-spacing:-.03em; } .sub { color:var(--ink2); margin-bottom:16px; }
.row { display:grid; grid-template-columns:minmax(90px, 132px) 1fr 76px; align-items:center; gap:10px; margin:6px 0; }
.name { color:var(--ink2); font-size:.9rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; } .val { text-align:right; font-size:.9rem; white-space:nowrap; }
.track { height:14px; } .bar { display:block; height:100%; background:var(--accent); border-radius:0 7px 7px 0; }
.stack { display:flex; gap:2px; height:18px; }
.seg { min-width:2px; } .seg:first-child { border-radius:9px 0 0 9px; } .seg:last-child { border-radius:0 9px 9px 0; }
.a { background:var(--accent); } .b { background:var(--muted); }
.legend { display:flex; gap:16px; flex-wrap:wrap; margin-top:10px; font-size:.9rem; color:var(--ink2); }
.sw { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; } .legend b { color:var(--ink); font-weight:600; }
.verdict { margin:16px 0 0; }
details { margin-top:12px; color:var(--ink2); } summary { cursor:pointer; }
table { width:100%; border-collapse:collapse; margin-top:8px; } td, th { padding:5px 6px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }
td:last-child, th:last-child { text-align:right; white-space:nowrap; }
small { color:var(--ink2); }
.month[hidden] { display:none; }
.foot { color:var(--ink2); font-size:.85rem; }
"""


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
                f"{block_categories(d, k, v)}{block_savings(d, k, v, partial, v == other)}{block_fixed(d, k, v)}"
                f"{block_limits(rows, v, viewer, settings_url)}{block_cash(d, k, v)}</div>"
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
<script>
const pt = document.querySelectorAll('#people button'), mt = document.querySelectorAll('#months button'), panels = document.querySelectorAll('.month');
let p = 'Разом', m = {json.dumps(month_id(default))};
function show() {{
  pt.forEach(t => t.setAttribute('aria-selected', t.dataset.p === p));
  mt.forEach(t => t.setAttribute('aria-selected', t.dataset.m === m));
  panels.forEach(x => x.hidden = x.dataset.p !== p || x.dataset.m !== m);
  try {{ localStorage.setItem('view', JSON.stringify({{p, m}})); }} catch (e) {{}}
}}
pt.forEach(t => t.addEventListener('click', () => {{ p = t.dataset.p; show(); }}));
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
