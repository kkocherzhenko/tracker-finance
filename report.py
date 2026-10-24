"""Збирає report.html: виконує збережені запити 1-3 з main.beancount і малює відповіді для Олі."""
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
LEDGER = str(ROOT / "main.beancount")
MONTH_NAMES = {8: "Серпень", 9: "Вересень", 10: "Жовтень"}
MONTH_GEN = {8: "серпня", 9: "вересня", 10: "жовтня"}
CATEGORY_NAMES = {"Краса-Побут": "Краса і побут", "Доставка-Їжі": "Доставка їжі"}

entries, errors, _ = loader.load_file(LEDGER)
if errors:
    raise SystemExit(f"У main.beancount є помилки: {errors[0]}")

queries = {e.name: e.query_string for e in entries if isinstance(e, data.Query)}
connection = beanquery.connect(f"beancount:{LEDGER}")


def run(name):
    cursor = connection.execute(queries[name])
    columns = [c.name for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def number(value):
    """Сума з запиту (Inventory або число) -> Decimal у злотих."""
    if isinstance(value, Decimal):
        return value
    return value.get_currency_units("PLN").number


# Запит 1: витрати за категоріями
categories = defaultdict(list)
for r in run("витрати-за-категоріями"):
    name = r["account"].split(":", 1)[1]
    categories[(r["year"], r["month"])].append((CATEGORY_NAMES.get(name, name.replace("-", " ").capitalize()), number(r["total"])))

# Запит 2: норма заощаджень (дата останньої операції показує неповний місяць)
savings = {(r["year"], r["month"]): r for r in run("норма-заощаджень")}

# Запит 3: фіксовані і змінні
fixed_split = defaultdict(dict)
for r in run("фіксовані-і-змінні"):
    fixed_split[(r["year"], r["month"])][bool(r["fixed"])] = number(r["total"])


def zl(x, decimals=2):
    return f"{x:,.{decimals}f}".replace(",", " ").replace(".", ",") + " зл"


def pct(a, b, decimals=0):
    return f"{a / b * 100:.{decimals}f}".replace(".", ",") + "%" if b else "—"


def month_caption(key):
    last = savings[key]["last_day"]
    end = date(key[0] + key[1] // 12, key[1] % 12 + 1, 1).toordinal() - 1
    if last.toordinal() < end - 2:
        return f"неповний: дані до {last.day} {MONTH_GEN[last.month]}"
    return "місяць закінчено"


def block_categories(key):
    rows = sorted(categories[key], key=lambda kv: -kv[1])
    total = sum(v for _, v in rows)
    top = rows[0][1]
    bars = "".join(
        f'<div class="row" title="{escape(n)}: {zl(v)}, {pct(v, total)} витрат">'
        f'<span class="name">{escape(n)}</span>'
        f'<span class="track"><span class="bar" style="width:{v / top * 100:.1f}%"></span></span>'
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
        f'<span class="seg {cls}" style="flex:{v}" title="{label}: {zl(v)}"></span>'
        for label, v, cls in parts
    )
    legend = "".join(
        f'<span class="key"><i class="sw {cls}"></i>{label} <b>{zl(v, 0)}</b> · {pct(v, total)}</span>'
        for label, v, cls in parts
    )
    return f'<div class="stack">{segs}</div><div class="legend">{legend}</div>'


def block_savings(key, partial):
    s = savings[key]
    income, spent, saved = number(s["income"]), number(s["spent"]), number(s["saved"])
    rate = pct(saved, income, 1)
    warn = " Місяць ще не закінчився, тому норма завищена." if partial else ""
    return f"""
<section class="card"><h2>2. Скільки відкладено</h2>
<div class="hero">{rate}</div><div class="sub">доходу відкладено ({zl(income, 0)} − {zl(spent, 0)})</div>
{stacked([("Відкладено", saved, "a"), ("Витрати", spent, "b")])}
<p class="verdict">Відкладено {zl(saved, 0)} із {zl(income, 0)}.{warn}</p></section>"""


def block_fixed(key):
    fixed, managed = fixed_split[key].get(True, Decimal(0)), fixed_split[key].get(False, Decimal(0))
    total = fixed + managed
    return f"""
<section class="card"><h2>3. Фіксовані й змінні</h2>
<div class="hero">{pct(fixed, total)}</div><div class="sub">витрат — фіксовані ({zl(fixed, 0)})</div>
{stacked([("Змінні", managed, "a"), ("Фіксовані", fixed, "b")])}
<p class="verdict">Змінних витрат, якими можна керувати, — {zl(managed, 0)}.</p></section>"""


keys = sorted(savings)
default = next((k for k in reversed(keys) if "закінчено" in month_caption(k)), keys[-1])
tabs, panels = [], []
for k in keys:
    cap = month_caption(k)
    partial = "неповний" in cap
    tabs.append(
        f'<button role="tab" data-m="{k[1]}" aria-selected="{str(k == default).lower()}">'
        f'{MONTH_NAMES[k[1]]}{" *" if partial else ""}</button>'
    )
    panels.append(
        f'<div class="month" data-m="{k[1]}"><p class="caption{" partial" if partial else ""}">'
        f"{MONTH_NAMES[k[1]]} {k[0]} · {cap}</p>"
        f"{block_categories(k)}{block_savings(k, partial)}{block_fixed(k)}</div>"
    )

html = f"""<!doctype html>
<html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Фінанси Олі</title>
<style>
:root {{ --surface:#f5f5f7; --card:#fff; --ink:#1d1d1f; --ink2:#6e6e73; --line:#e5e5ea; --accent:#0071e3; --muted:#c7c7cc; --warn:#fff4d6; --seg:#e3e3e8; --glass:rgba(245,245,247,.8); }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --surface:#000; --card:#1c1c1e; --ink:#f5f5f7; --ink2:#98989d; --line:#2c2c2e; --accent:#0a84ff; --muted:#48484a; --warn:#3a2f0b; --seg:#2c2c2e; --glass:rgba(0,0,0,.75); }} }}
:root[data-theme="dark"] {{ --surface:#000; --card:#1c1c1e; --ink:#f5f5f7; --ink2:#98989d; --line:#2c2c2e; --accent:#0a84ff; --muted:#48484a; --warn:#3a2f0b; --seg:#2c2c2e; --glass:rgba(0,0,0,.75); }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--surface); color:var(--ink); font:16px/1.5 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", system-ui, sans-serif; -webkit-font-smoothing:antialiased; }}
main {{ max-width:720px; margin:0 auto; padding:0 16px 48px; }}
header {{ padding:24px 0 8px; }} h1 {{ margin:0; font-size:2.1rem; font-weight:700; letter-spacing:-.02em; }}
.tabs {{ display:flex; gap:2px; padding:8px 0; position:sticky; top:0; z-index:1; background:var(--glass); backdrop-filter:saturate(180%) blur(20px); -webkit-backdrop-filter:saturate(180%) blur(20px); }}
.tabs button:first-child {{ border-radius:9px 0 0 9px; }} .tabs button:last-child {{ border-radius:0 9px 9px 0; }}
.tabs button {{ flex:1; font:inherit; font-size:.9rem; color:var(--ink); background:var(--seg); border:0; border-radius:0; padding:7px 12px; cursor:pointer; }}
.tabs button[aria-selected="true"] {{ background:var(--accent); color:#fff; font-weight:600; }}
.caption {{ color:var(--ink2); margin:12px 0; }} .caption.partial {{ background:var(--warn); border-radius:12px; padding:8px 14px; color:var(--ink); }}
.card {{ background:var(--card); border-radius:20px; padding:24px; margin:16px 0; box-shadow:0 1px 2px rgba(0,0,0,.04), 0 4px 16px rgba(0,0,0,.04); }}
h2 {{ margin:0 0 8px; font-size:.95rem; color:var(--ink2); font-weight:600; }}
.hero {{ font-size:3.25rem; line-height:1.1; font-weight:700; letter-spacing:-.03em; }} .sub {{ color:var(--ink2); margin-bottom:16px; }}
.row {{ display:grid; grid-template-columns:132px 1fr 76px; align-items:center; gap:10px; margin:6px 0; }}
.name {{ color:var(--ink2); font-size:.9rem; }} .val {{ text-align:right; font-size:.9rem; white-space:nowrap; }}
.track {{ height:14px; }} .bar {{ display:block; height:100%; background:var(--accent); border-radius:0 7px 7px 0; }}
.stack {{ display:flex; gap:2px; height:18px; }}
.seg {{ min-width:2px; }} .seg:first-child {{ border-radius:9px 0 0 9px; }} .seg:last-child {{ border-radius:0 9px 9px 0; }}
.a {{ background:var(--accent); }} .b {{ background:var(--muted); }}
.legend {{ display:flex; gap:16px; flex-wrap:wrap; margin-top:10px; font-size:.9rem; color:var(--ink2); }}
.sw {{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; }} .legend b {{ color:var(--ink); font-weight:600; }}
.verdict {{ margin:16px 0 0; }}
details {{ margin-top:12px; color:var(--ink2); }} summary {{ cursor:pointer; }}
table {{ width:100%; border-collapse:collapse; margin-top:8px; }} td, th {{ padding:5px 6px; border-bottom:1px solid var(--line); text-align:left; }}
td+td, th+th {{ text-align:right; }}
.month[hidden] {{ display:none; }}
.foot {{ color:var(--ink2); font-size:.85rem; }}
</style></head><body><main>
<header><h1>Фінанси Олі</h1></header>
<div class="tabs" role="tablist">{''.join(tabs)}</div>
{''.join(panels)}
<p class="foot">* місяць ще не закінчився. Дані: виписка за 1 серпня — 15 жовтня 2026, злоті.</p>
</main>
<script>
const tabs = document.querySelectorAll('.tabs button'), panels = document.querySelectorAll('.month');
function show(m) {{
  tabs.forEach(t => t.setAttribute('aria-selected', t.dataset.m === m));
  panels.forEach(p => p.hidden = p.dataset.m !== m);
  try {{ localStorage.setItem('month', m); }} catch (e) {{}}
}}
tabs.forEach(t => t.addEventListener('click', () => show(t.dataset.m)));
let start = {json.dumps(str(default[1]))};
try {{ const s = localStorage.getItem('month'); if (s && [...tabs].some(t => t.dataset.m === s)) start = s; }} catch (e) {{}}
show(start);
</script>
</body></html>"""

(ROOT / "report.html").write_text(html, encoding="utf-8")
print("Записано report.html")
