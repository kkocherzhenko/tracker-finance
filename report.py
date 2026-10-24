"""Збирає звіт: виконує збережені запити з main.beancount і малює відповіді для Олі й Марка.

`uv run python report.py` пише report.html (без інтернету, відкривається в браузері).
Веб-застосунок (app.py) викликає render() на кожен запит, тож звіт завжди свіжий.
"""
import calendar
import csv
import json
import math
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


# Іконки категорій (лінії 24×24, як у нижньому меню). Ключ — назва з category_name().
ICONS = {
    "Продукти": '<path d="M3 9h18l-2 11H5z"/><path d="M8 9l4-6 4 6"/>',
    "Житло": '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>',
    "Доставка їжі": '<circle cx="6" cy="17" r="2.5"/><circle cx="18" cy="17" r="2.5"/><path d="M8.5 17h7M14 6h3l1.5 8.5M6 14.5V10h5l3 4"/>',
    "Кафе": '<path d="M4 8h13v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5z"/><path d="M17 10h2a2 2 0 0 1 0 4h-2M8 3v2M12 3v2"/>',
    "Транспорт": '<rect x="5" y="3" width="14" height="14" rx="2"/><path d="M5 11h14M8 17v3M16 17v3"/>',
    "Спорт": '<path d="M6 7v10M18 7v10M3 10v4M21 10v4M6 12h12"/>',
    "Підписки": '<path d="M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3"/><path d="M18 3v4h-4M6 21v-4h4"/>',
    "Мобільний оператор": '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
    "Інтернет": '<path d="M2 9a15 15 0 0 1 20 0M5 13a10 10 0 0 1 14 0M8.5 16.5a5 5 0 0 1 7 0"/><path d="M12 20h.01"/>',
    "Електрика": '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    "Покупки": '<path d="M5 8h14l-1 12H6z"/><path d="M9 8a3 3 0 0 1 6 0"/>',
    "Краса і побут": '<path d="M12 3l2 5.5 5.5 1.5-5.5 2-2 6-2-6-5.5-2 5.5-1.5z"/>',
    "Розваги": '<path d="M3 7h18v3a2 2 0 0 0 0 4v3H3v-3a2 2 0 0 0 0-4z"/><path d="M14 7v10"/>',
    "Інше": '<path d="M6 12h.01M12 12h.01M18 12h.01"/>',
    "Без категорії": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.5V14M12 17.5h.01"/>',
}


def icon(name):
    """SVG-іконка категорії; невідома категорія — перша літера."""
    if name in ICONS:
        return f'<svg viewBox="0 0 24 24" aria-hidden="true">{ICONS[name]}</svg>'
    return f'<span aria-hidden="true">{escape(name[:1])}</span>'


def category_name(leaf):
    return CATEGORY_NAMES.get(leaf, leaf.replace("-", " ").capitalize())


def zl(x, decimals=2):
    return f"{x:,.{decimals}f}".replace(",", " ").replace(".", ",") + " зл"


def zl_html(x, decimals=0):
    """Як zl(), але «зл» менше і сірим — для великих сум. zl() лишається текстом для title і тестів."""
    return zl(x, decimals)[:-3] + '<span class="cur">зл</span>'


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


def delta_chip(d, key, view, total, partial):
    """«▲ 12% до серпня»: витрати проти попереднього місяця. Для неповного — «дані до …», для першого — нічого."""
    if partial:
        last = d["last_day"][key]
        return f'<span class="chip info">дані до {last.day} {MONTH_GEN[last.month]}</span>'
    i = d["keys"].index(key)
    prev = sum(d["categories"].get((d["keys"][i - 1], view), {}).values()) if i else 0
    if prev <= 0:
        return ""
    up = total > prev
    return (f'<span class="chip {"bad" if up else "good"}">{"▲" if up else "▼"} '
            f'{pct(abs(total - prev), prev)} до {MONTH_GEN[d["keys"][i - 1][1]]}</span>')


def block_categories(d, key, view, partial):
    rows = sorted(d["categories"][key, view].items(), key=lambda kv: -kv[1])
    if not rows:
        return empty("Куди йдуть гроші", SECTIONS[0][2], "Витрат за цей місяць немає.")
    total = sum(v for _, v in rows)
    top = rows[0][1] or Decimal(1)
    bars = "".join(
        f'<div class="row" title="{escape(n)}: {zl(v)}, {pct(v, total)} витрат">'
        f'<span class="ico">{icon(n)}</span><span class="name">{escape(n)}</span><span class="val">{zl(v, 0)}</span>'
        f'<span class="meta"><small>{pct(v, total)}</small>'
        f'<span class="track"><span class="bar" style="width:{max(v, 0) / top * 100:.1f}%"></span></span></span></div>'
        for n, v in rows
    )
    legend = "".join(
        f'<li><i class="sw" style="background:var(--cat{i % 8 + 1}){"; opacity:.6" if i >= 8 else ""}"></i>{escape(n)} <b>{pct(v, total)}</b></li>'
        for i, (n, v) in enumerate(rows)
    )
    # Два слайди однієї картки (scroll-snap): 1 — сума і список, 2 — кільце із сумою в центрі. Сума видна один раз.
    return f"""
<section class="card spend"><div class="cardhead"><h2>Куди йдуть гроші</h2><button type="button" class="slidetoggle">Діаграма</button></div>
<div class="slides" tabindex="0" aria-label="Витрати: список і діаграма, стрілки вліво і вправо перемикають">
<div class="slide"><div class="hero">{zl_html(total)}</div><div class="sub">витрачено за місяць {delta_chip(d, key, view, total, partial)}</div>
<div class="chart">{bars}</div>
</div>
<div class="slide">{donut(rows, total)}<ul class="dlegend">{legend}</ul></div>
</div>
<div class="dots"><button type="button" aria-label="Список" aria-current="true"></button><button type="button" aria-label="Діаграма" aria-current="false"></button></div>
<p class="swipehint" hidden>Свайпніть, щоб побачити діаграму</p></section>"""


def donut(rows, total):
    """Кільце до 320 px (масштабується з viewBox): сегменти в порядку рядків, кольори --cat1..8 (понад 8 — ті самі з прозорістю), проміжки 2 px."""
    r, c = 71, 2 * math.pi * 71
    segs, start = [], 0.0
    for i, (_, v) in enumerate(rows):
        share = float(max(v, 0) / total) if total > 0 else 0
        if share * c > 2:
            fade = "; opacity:.6" if i >= 8 else ""
            segs.append(f'<circle r="{r}" cx="80" cy="80" style="stroke:var(--cat{i % 8 + 1}){fade}" '
                        f'stroke-dasharray="{share * c - 2:.2f} {c:.2f}" stroke-dashoffset="{-start:.2f}"/>')
        start += share * c
    return (f'<div class="donut"><svg viewBox="0 0 160 160" aria-hidden="true"><g transform="rotate(-90 80 80)">{"".join(segs)}</g></svg>'
            f'<div><b>{zl_html(total)}</b><small>витрачено</small></div></div>')


def ring(percent, label, negative=False):
    """Кільце 140 px: дуга = percent (0–100, за модулем), у центрі label і «відкладено»."""
    r, c = 63, 2 * math.pi * 63
    arc = min(abs(float(percent)), 100) / 100 * c
    return (f'<div class="ring{" neg" if negative else ""}"><svg viewBox="0 0 140 140" aria-hidden="true"><g transform="rotate(-90 70 70)">'
            f'<circle class="rtrack" r="{r}" cx="70" cy="70"/><circle class="rarc" r="{r}" cx="70" cy="70" stroke-dasharray="{arc:.2f} {c:.2f}"/>'
            f'</g></svg><div><b>{label}</b><small>відкладено</small></div></div>')


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
        return empty("Скільки відкладено", PEAK, f"Доходи й заощадження {view} бачить лише {view}.")
    s = d["savings"][key, view]
    income, spent, saved = s["income"], s["spent"], s["saved"]
    if not income:
        return empty("Скільки відкладено", PEAK,
                     f"Доходу за цей місяць у даних ще немає. Витрачено {zl(spent, 0)}. Норму заощаджень порахуємо, коли надійде зарплата.")
    rate = pct(saved, income, 1)
    warn = " Місяць ще не закінчився, тому норма завищена." if partial else ""
    bar = stacked([("Відкладено", saved, "a"), ("Витрати", spent, "b")]) if saved > 0 else ""
    return f"""
<section class="card"><h2>Скільки відкладено</h2>
{ring(saved / income * 100, rate, saved < 0)}<div class="sub center">доходу відкладено ({zl(income, 0)} − {zl(spent, 0)})</div>
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
    """Заголовок і рядок плашок, що гортається вбік; дотик відкриває вкладку «Ліміти»."""
    chips = "".join(
        f'<span class="achip {level(s, l)[0]}">{escape(n)} <b>{f"+{zl(s - l, 0)}" if s > l else pct(s, l)}</b></span>'
        for n, s, l in rows if level(s, l)[0] != "fine"
    )
    if not chips:
        return ""
    return (f'<div class="alert" role="alert"><button type="button" class="atitle">Увага, ліміти <span aria-hidden="true">›</span></button>'
            f'<div class="achips">{chips}</div></div>')


STATE = {"fine": "В нормі", "near": "Близько", "over": "Перевищено"}


# Мала гора з пунктирною тропою і прапорцем — спрощений знак trajet-zigzag з logo/ (порожні стани «Відкладено» і «Ліміти»).
PEAK = ('<svg class="peak" viewBox="0 0 64 48" aria-hidden="true"><path class="hill" d="M2 46 L30 6 L38 14 L62 46 Z"/>'
        '<path class="path" d="M14 44 C24 40 34 38 26 32 S 22 22 30 18 S 34 10 30 8"/><circle cx="14" cy="44" r="2.5"/>'
        '<path class="flag" d="M30 8 V1 l6 2.2 -6 2.2"/></svg>')
# Тропа на гору для ліміту: вершина — ліміт. Точки схилу в координатах viewBox 0 -10 300 44.
CLIMB = [(4, 32), (70, 28), (130, 21), (190, 12), (240, 3)]


def climb_point(frac):
    """Точка на тропі, що пройдена на frac (0..1) довжини."""
    seg = [(a, b, math.dist(a, b)) for a, b in zip(CLIMB, CLIMB[1:])]
    left = frac * sum(l for *_, l in seg)
    for (x1, y1), (x2, y2), l in seg:
        if left <= l:
            return x1 + (x2 - x1) * left / l, y1 + (y2 - y1) * left / l
        left -= l
    return CLIMB[-1]


def climb(spent, limit, today=None):
    """SVG: силует гори, пунктирна тропа, пройдена частина кольором стану, прапорець на вершині, риска «сьогодні»."""
    frac = min(float(spent / limit), 1) if limit else 1
    path = " ".join(f"{x},{y}" for x, y in CLIMB)
    mark = ""
    if today is not None:
        x, y = climb_point(today)
        mark = f'<path class="now" d="M{x:.1f} {y - 6:.1f} V{y + 6:.1f}"/>'
    return (f'<svg class="climb" viewBox="0 -10 300 44" aria-hidden="true">'
            f'<path class="hill" d="M0 34 L70 30 L130 23 L190 14 L240 4 L262 16 L300 34 Z"/>'
            f'<polyline class="trail" points="{path}"/><polyline class="done" points="{path}" pathLength="100" stroke-dasharray="{frac * 100:.1f} 100"/>'
            f'<path class="flag" d="M240 3 V-9 l9 3.2 -9 3.2"/>{mark}</svg>')


def empty(title, svg, text, action=""):
    """Порожня картка: іконка (або готовий <svg>, як PEAK), одне речення і дія, якщо є."""
    icon_html = svg if svg.startswith("<svg") else f'<svg viewBox="0 0 24 24" aria-hidden="true">{svg}</svg>'
    return (f'<section class="card empty"><h2>{title}</h2>{icon_html}'
            f'<p>{text}</p>{action}</section>')


def block_limits(rows, view, viewer, settings_url, last=None):
    """last — остання дата даних неповного місяця: тоді показуємо позначку «сьогодні» і скільки можна на день."""
    if viewer and view not in ("Разом", viewer):
        return empty("Ліміти", PEAK, f"Ліміти {view} бачить лише {view}.")
    if not rows:
        action = f'<a class="btn" href="{settings_url}">Задати ліміт</a>' if settings_url else ""
        return empty("Ліміти", PEAK, "Лімітів ще немає.", action)
    days = calendar.monthrange(last.year, last.month)[1] if last else 0
    items = []
    for n, spent, limit in rows:
        state = level(spent, limit)[0]
        if spent > limit:
            note = f"перевищено на {zl(spent - limit, 0)}"
        else:
            note = f"Лишилось {zl(limit - spent, 0)}"
            if last and days > last.day:
                note += f" · ≈ {zl((limit - spent) / (days - last.day), 0)}/день"
        items.append(
            f'<div class="limit {state}"><div class="lhead"><span>{escape(n)} <span class="lchip">{STATE[state]}</span></span>'
            f'<span>{zl(spent, 0)} з {zl(limit, 0)}</span></div>'
            f'{climb(spent, limit, last.day / days if last else None)}'
            f'<small>{note}</small></div>'
        )
    link = f'<p class="foot"><a href="{settings_url}">Налаштувати ліміти</a></p>' if settings_url else ""
    return f'<section class="card"><h2>Ліміти на місяць</h2>{"".join(items)}{link}</section>'


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
html { background:var(--bg); } /* без білого спалаху до першого кадру */
/* Заставка: кінцевий стан — у базових стилях, анімації з backwards, тож без руху видно готовий знак */
#splash { position:fixed; inset:0; z-index:10; display:grid; place-items:center; padding:24px; background:var(--bg); animation:sp-out .3s 2.2s ease-in forwards; }
#splash svg { width:min(300px, 72vw); height:auto; overflow:visible; }
#sp-mountain { animation:sp-rise .7s ease-out backwards; }
.sp-rim { fill:var(--accent); } .sp-ice { fill:var(--bg); stroke:var(--border); stroke-width:6; } .sp-shade { fill:var(--accent); }
.sp-snow { fill:var(--surface); stroke:var(--border); stroke-width:6; stroke-linejoin:round; } .sp-snow2 { fill:var(--border); } .sp-rock { fill:var(--text); }
#sp-path path { fill:none; stroke:var(--text); stroke-width:6px; stroke-linecap:round; stroke-dasharray:1; stroke-dashoffset:0; }
.sp-low { animation:sp-draw .6s .7s ease-in-out backwards; } .sp-high { animation:sp-draw .35s 1.4s ease-out backwards; }
.sp-dot { fill:var(--text); stroke:var(--surface); stroke-width:4; animation:sp-fade .2s .6s ease-out backwards; }
#sp-flag { transform-box:fill-box; transform-origin:0 100%; animation:sp-pop .15s 1.75s ease-out backwards; }
.sp-pole { stroke:var(--text); stroke-width:6; stroke-linecap:round; } .sp-pennant { fill:var(--text); }
#sp-wordmark { animation:sp-fade .3s 1.9s ease-out backwards; }
#sp-wordmark text { fill:var(--text); font:700 150px Inter, -apple-system, BlinkMacSystemFont, system-ui, sans-serif; letter-spacing:-4px; }
@keyframes sp-rise { from { opacity:0; transform:translateY(24px); } }
@keyframes sp-draw { from { stroke-dashoffset:1; } }
@keyframes sp-fade { from { opacity:0; } }
@keyframes sp-pop { from { opacity:0; transform:scale(.4); } }
@keyframes sp-out { to { opacity:0; visibility:hidden; } }
body { margin:0; background:var(--bg); color:var(--text); font:16px/1.5 Inter, -apple-system, BlinkMacSystemFont, system-ui, sans-serif; -webkit-font-smoothing:antialiased; font-variant-numeric:tabular-nums; } /* суми однакової ширини цифр */
main { max-width:720px; margin:0 auto; padding:0 24px calc(160px + env(safe-area-inset-bottom, 0px)); /* кінець сторінки не ховається під «+» (84 + 60 + 16) */ padding-top:env(safe-area-inset-top, 0); }
header { display:flex; align-items:center; gap:12px; margin:0 -24px; padding:14px 24px; border-bottom:1px solid var(--border); }
h1 { margin:0; flex:1; font-size:1.25rem; font-weight:600; letter-spacing:-.01em; }
header h1 { display:flex; align-items:center; } /* без запасу під базову лінію: знак по центру з «пігулкою» */
.brand { display:inline-flex; align-items:center; gap:8px; min-height:44px; color:var(--text, #1e3550); text-decoration:none; }
.brand svg { flex:none; } .brand-name { font-size:20px; font-weight:600; letter-spacing:-.01em; }
.nav { display:flex; gap:8px; align-items:center; }
.btn { font:inherit; font-size:1rem; font-weight:600; border:0; border-radius:999px; padding:10px 20px; min-height:44px; display:inline-flex; align-items:center; justify-content:center; background:var(--accent-strong); color:var(--on-accent); text-decoration:none; cursor:pointer; }
.btn.ghost { background:var(--border); color:var(--text); }
.sticky { position:sticky; top:0; z-index:1; background:var(--bg); padding:12px 0 4px; }
.tabs { display:flex; }
#people { background:var(--border); border-radius:999px; padding:4px; }
#people button { flex:1; min-height:44px; font:inherit; font-size:.95rem; color:var(--text); background:none; border:0; border-radius:999px; cursor:pointer; }
#people button[aria-selected="true"] { background:var(--accent-strong); color:var(--on-accent); font-weight:600; }
#months { justify-content:center; gap:4px; margin-top:4px; }
#months button { min-height:44px; padding:0 12px; font:inherit; font-size:.95rem; font-weight:500; color:var(--text-muted); background:none; border:0; border-bottom:2px solid transparent; cursor:pointer; }
#months button[aria-selected="true"] { color:var(--text); font-weight:600; border-bottom-color:var(--accent); }
.flash { position:fixed; z-index:2; left:24px; right:24px; bottom:calc(96px + env(safe-area-inset-bottom, 0px)); max-width:672px; margin:0 auto; background:var(--accent-strong); color:var(--on-accent); border-radius:999px; padding:14px 20px; animation:toast 5s forwards; }
@keyframes toast { 0%, 85% { opacity:1; } 100% { opacity:0; visibility:hidden; } }
.alert { background:var(--surface); border:1px solid color-mix(in srgb, var(--warning) 40%, var(--surface)); border-radius:24px; padding:12px 16px; margin:16px 0 0; cursor:pointer; }
.atitle { display:block; width:100%; min-height:32px; padding:0; border:0; background:none; font:inherit; font-weight:600; color:var(--text); text-align:left; cursor:pointer; }
.achips { display:flex; gap:8px; margin-top:6px; overflow-x:auto; white-space:nowrap; scrollbar-width:none; } .achips::-webkit-scrollbar { display:none; }
.achip { flex:none; padding:6px 12px; border-radius:999px; font-size:.85rem; } .achip.over { background:var(--negative-soft); } .achip.near { background:var(--warning-soft); }
.tabbar { position:fixed; z-index:1; left:0; right:0; bottom:0; display:flex; justify-content:center; padding:6px 8px env(safe-area-inset-bottom, 0px); background:var(--surface); border:1px solid var(--border); border-bottom:0; border-radius:28px 28px 0 0; }
.tabbar button { flex:1; max-width:180px; min-height:56px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:2px; font:inherit; font-size:.7rem; color:var(--text-muted); background:none; border:0; cursor:pointer; }
.tabbar button[aria-selected="true"] { color:var(--accent-strong); font-weight:600; } .tabbar button[aria-selected="true"] svg { stroke:var(--accent); }
.tabbar svg { width:26px; height:26px; fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }
.fab { position:fixed; z-index:1; right:max(24px, calc(50% - 336px)); bottom:calc(84px + env(safe-area-inset-bottom, 0px)); width:60px; height:60px; border-radius:50%; display:flex; align-items:center; justify-content:center; background:var(--accent-strong); color:var(--on-accent); font-size:2rem; font-weight:300; text-decoration:none; }
.menu { position:relative; margin-top:0; } /* загальне details{margin-top} лишилось від таблиці й зсувало «пігулку» вниз */ .menu summary::-webkit-details-marker { display:none; }
.menu summary { list-style:none; display:flex; align-items:center; min-height:44px; padding:0 16px; border:1.5px solid var(--text); border-radius:999px; font-weight:600; cursor:pointer; }
.menu-list { position:absolute; right:0; top:calc(100% + 8px); z-index:3; min-width:210px; display:flex; flex-direction:column; padding:6px; background:var(--surface); border:1px solid var(--border); border-radius:24px; }
.menu-list a, .menu-list button { display:flex; align-items:center; width:100%; min-height:48px; padding:0 16px; border:0; border-radius:18px; background:none; color:var(--text); font:inherit; text-align:left; text-decoration:none; cursor:pointer; }
.menu-list a:hover, .menu-list button:hover { background:var(--border); } .menu-list form { margin:0; }
.card { background:var(--surface); border:1px solid var(--border); border-radius:24px; padding:24px; margin:16px 0; }
h2 { margin:0 0 12px; font-size:.75rem; color:var(--text-muted); font-weight:600; letter-spacing:.05em; text-transform:uppercase; }
.cur { font-size:.5em; font-weight:500; color:var(--text-muted); margin-left:.15em; letter-spacing:0; }
.ring { position:relative; width:140px; height:140px; margin:4px auto 8px; }
.ring svg { width:100%; height:100%; } .ring circle { fill:none; stroke-width:14; } .rtrack { stroke:var(--border); }
.rarc { stroke:var(--accent); stroke-linecap:round; animation:draw .4s ease-out; } .ring.neg .rarc { stroke:var(--negative); }
@keyframes draw { from { stroke-dasharray:0 999; } }
.ring div { position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; }
.ring b { font-size:2rem; font-weight:600; letter-spacing:-.02em; line-height:1.1; } .ring small { font-size:.8rem; }
.sub.center { text-align:center; }
.chip { display:inline-flex; align-items:center; gap:4px; margin-left:6px; padding:3px 10px; border-radius:999px; font-size:.8rem; font-weight:600; color:var(--text); white-space:nowrap; }
.chip.bad { background:var(--negative-soft); } .chip.info { background:var(--warning-soft); font-weight:500; } .chip.good { background:color-mix(in srgb, var(--positive) 14%, var(--surface)); }
.hero { font-size:3.5rem; line-height:1.1; font-weight:600; letter-spacing:-.03em; } .sub { color:var(--text-muted); margin:4px 0 20px; }
.donut { position:relative; width:min(320px, 100%); aspect-ratio:1; margin:8px auto 20px; } /* удвічі від 160 px, але не ширше картки */
.donut svg { display:block; width:100%; height:100%; } .donut circle { fill:none; stroke-width:18; }
.donut div { position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; }
.donut b { font-size:2.5rem; font-weight:600; letter-spacing:-.03em; } .donut small { font-size:1rem; }
.row { display:grid; grid-template-columns:36px 1fr auto; grid-template-areas:"ico name val" "ico meta meta"; column-gap:12px; row-gap:2px; align-items:center; min-height:48px; padding:6px 0; }
.ico { grid-area:ico; width:36px; height:36px; border-radius:50%; display:flex; align-items:center; justify-content:center; background:color-mix(in srgb, var(--c) 18%, var(--surface)); color:var(--text); font-weight:600; }
.ico svg { width:20px; height:20px; fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }
.name { grid-area:name; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; } .val { grid-area:val; text-align:right; font-weight:600; white-space:nowrap; }
.meta { grid-area:meta; display:flex; align-items:center; gap:8px; } .meta small { min-width:2.6em; font-size:.8rem; }
.track { flex:1; height:6px; background:color-mix(in srgb, var(--border) 40%, var(--surface)); /* світліше за --cat5, щоб її смугу було видно */ border-radius:3px; overflow:hidden; } .bar { display:block; height:100%; background:var(--c, var(--accent)); border-radius:3px; }
.row:nth-child(8n+1) { --c:var(--cat1); } .row:nth-child(8n+2) { --c:var(--cat2); } .row:nth-child(8n+3) { --c:var(--cat3); } .row:nth-child(8n+4) { --c:var(--cat4); } .row:nth-child(8n+5) { --c:var(--cat5); } .row:nth-child(8n+6) { --c:var(--cat6); } .row:nth-child(8n+7) { --c:var(--cat7); } .row:nth-child(8n+0) { --c:var(--cat8); }
.row:nth-child(n+9) .bar { opacity:.6; } /* понад 8 категорій — ті самі кольори, але прозоріші */
.stack { display:flex; gap:2px; height:14px; }
.seg { min-width:2px; } .seg:first-child { border-radius:7px 0 0 7px; } .seg:last-child { border-radius:0 7px 7px 0; }
.a { background:var(--cat1); } .b { background:var(--cat2); }
.legend { display:flex; gap:16px; flex-wrap:wrap; margin-top:12px; font-size:.9rem; color:var(--text-muted); }
.sw { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; } .legend b { color:var(--text); font-weight:600; }
.limit { padding:14px 0; border-bottom:1px solid var(--border); } .limit:last-of-type { border-bottom:0; }
.lhead { display:flex; justify-content:space-between; align-items:center; gap:8px; } .lhead > span:last-child { font-weight:600; white-space:nowrap; }
.lchip { display:inline-block; margin-left:4px; padding:1px 8px; border-radius:999px; font-size:.72rem; font-weight:600; vertical-align:1px; }
.fine .lchip { background:color-mix(in srgb, var(--positive) 14%, var(--surface)); } .near .lchip { background:var(--warning-soft); } .over .lchip { background:var(--negative-soft); }
/* Ліміт — підйом на гору з логотипа: пройдене кольором стану, вершина з прапорцем = ліміт */
.fine { --state:var(--positive); } .near { --state:var(--warning); } .over { --state:var(--negative); }
.climb { display:block; width:100%; height:auto; margin:6px 0 2px; overflow:visible; }
.climb .hill { fill:color-mix(in srgb, var(--border) 50%, var(--surface)); } .climb polyline { fill:none; stroke-width:3; stroke-linecap:round; stroke-linejoin:round; }
.climb .trail { stroke:var(--text-muted); stroke-width:1.5; stroke-dasharray:4 4; } .climb .done { stroke:var(--state); animation:draw .4s ease-out; }
.climb .flag { fill:var(--state); stroke:var(--text); stroke-width:1.2; stroke-linejoin:round; } .climb .now { stroke:var(--text); stroke-width:2; }
.empty > .peak { width:64px; height:48px; overflow:visible; stroke:none; } .peak .hill { fill:var(--bg); }
.peak .path { fill:none; stroke:var(--text); stroke-width:1.6; stroke-dasharray:3 3; stroke-linecap:round; }
.peak circle { fill:var(--text); } .peak .flag { fill:var(--accent-strong); stroke:var(--text); stroke-width:1.2; stroke-linejoin:round; }
@keyframes grow { from { transform:scaleX(0); } }
.empty { text-align:center; } .empty h2 { text-align:left; } .empty > svg { width:40px; height:40px; margin:8px auto 0; fill:none; stroke:var(--accent); stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; } .empty p { margin:8px 0 16px; }
/* Рух: розділ з'являється знизу, смуги й кільця ростуть, коли розділ показано (анімація стартує з display:none заново). */
.month [data-s]:not([hidden]) { animation:rise .18s ease-out; }
@keyframes rise { from { opacity:0; transform:translateY(6px); } }
.bar { transform-origin:left; animation:grow .4s ease-out; } .donut circle { animation:draw .4s ease-out; }
.btn:active, .tabs button:active, .fab:active, .tabbar button:active, .alert:active { transform:scale(.98); }
.cardhead { display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:8px; } .cardhead h2 { margin:0; }
.slidetoggle { min-height:44px; padding:0 14px; border:0; border-radius:999px; background:var(--border); color:var(--text); font:inherit; font-size:.85rem; font-weight:600; cursor:pointer; }
.slides { display:flex; overflow-x:auto; scroll-snap-type:x mandatory; overscroll-behavior-x:contain; scrollbar-width:none; }
.slides::-webkit-scrollbar { display:none; } .slides:focus-visible { outline:2px solid var(--accent); outline-offset:4px; border-radius:12px; }
.slide { flex:0 0 100%; min-width:0; scroll-snap-align:start; scroll-snap-stop:always; }
.chart { padding-bottom:76px; } /* «+» (60 px) + 16 px: плаваюча кнопка не закриває суми останніх рядків */
.dlegend { list-style:none; margin:0; padding:0; display:grid; grid-template-columns:1fr 1fr; gap:8px 16px; font-size:.9rem; }
.dlegend li { display:flex; align-items:center; gap:6px; min-width:0; } .dlegend b { margin-left:auto; font-weight:600; }
.dots { display:flex; justify-content:center; gap:4px; margin-top:8px; }
.dots button { display:grid; place-items:center; width:44px; height:44px; padding:0; border:0; background:none; cursor:pointer; }
.dots button::before { content:""; width:8px; height:8px; border-radius:50%; background:var(--border); } .dots button[aria-current="true"]::before { background:var(--accent-strong); }
.swipehint { margin:0; text-align:center; color:var(--text-muted); font-size:.85rem; }
@media (prefers-reduced-motion: reduce) { *:not(.flash) { animation:none !important; transition:none !important; } }
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


# Заставка при холодному старті: знак trajet-spiral з logo/, перемальований окремими групами, щоб анімувати CSS.
# Гора з'являється (0–0,7 с), тропа малюється (0,7–1,75 с), прапорець (до 1,9 с), назва (до 2,2 с), згасання (до 2,5 с).
SPLASH = """<div id="splash" aria-hidden="true"><svg viewBox="40 0 900 960">
<g id="sp-mountain">
<path class="sp-rim" d="M50 566 L905 576 L910 616 L855 656 L865 706 L795 716 L885 756 L905 796 L545 786 L295 716 L285 666 L155 656 L145 606 Z"/>
<path class="sp-ice" d="M50 552 L905 562 L910 602 L855 642 L865 692 L795 702 L885 742 L905 782 L545 772 L295 702 L285 652 L155 642 L145 592 Z"/>
<path class="sp-shade" d="M70 545 L190 430 L230 350 L330 230 L400 190 L490 80 L470 560 Z"/>
<path class="sp-snow" d="M490 80 L600 190 L640 260 L760 380 L860 470 L905 560 L470 560 Z"/>
<path class="sp-snow2" d="M470 300 L540 380 L700 350 L770 430 L790 530 L470 545 Z"/>
<path class="sp-rock" d="M62 548 C110 520 150 500 165 470 C180 500 175 530 200 520 C215 470 220 440 240 435 C270 450 270 520 300 545 C330 520 340 470 360 470 C380 500 370 540 420 545 C470 520 480 440 500 430 C520 470 510 520 540 545 C590 530 600 460 620 465 C640 500 640 530 700 520 C720 470 740 400 760 395 C790 450 800 480 840 470 C870 500 895 545 905 575 C700 560 400 580 200 590 C130 588 80 575 62 548 Z"/>
</g>
<g id="sp-path">
<circle class="sp-dot" cx="473" cy="658" r="14"/>
<path class="sp-low" pathLength="1" vector-effect="non-scaling-stroke" d="M473 658 C640 610 860 575 905 540 C960 495 900 430 800 405"/>
<path class="sp-high" pathLength="1" vector-effect="non-scaling-stroke" d="M205 310 C330 300 520 270 590 220 C640 180 600 130 490 80"/>
</g>
<g id="sp-flag"><path class="sp-pole" d="M490 82 V12"/><path class="sp-pennant" d="M494 14 L528 27 L494 40 Z"/></g>
<g id="sp-wordmark"><text x="490" y="925" text-anchor="middle">trajet</text></g>
</svg></div>
<script>
// Лише раз за сесію браузера (холодний старт); при повторних переходах заставку прибираємо ще до показу.
(() => {
  const sp = document.getElementById('splash');
  try { if (sessionStorage.getItem('splash')) { sp.remove(); return; } sessionStorage.setItem('splash', '1'); } catch (e) {}
  const done = () => sp.remove();
  sp.addEventListener('animationend', e => { if (e.animationName === 'sp-out') done(); });
  sp.addEventListener('click', done);  // дотик — пропустити
  setTimeout(done, matchMedia('(prefers-reduced-motion: reduce)').matches ? 600 : 3000);  // не довше 3 с, навіть без подій
})();
</script>"""


# Знак Trajet для шапки (той самий, що static/logo/trajet-mark.svg). Дорога — виріз маскою, тож знак працює на будь-якому тлі.
BRAND = """<a class="brand" href="/" aria-label="Trajet"><svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true" focusable="false">
<defs><mask id="trajet-road" maskUnits="userSpaceOnUse" x="0" y="0" width="32" height="32"><rect width="32" height="32" fill="#fff"/>
<path d="M3.2 24.8C10 25.6 20 24 25.4 19.6M8.6 15.6C12.6 15.8 16.2 14.8 18.4 12.6" fill="none" stroke="#000" stroke-width="2.2" stroke-linecap="round"/></mask></defs>
<g mask="url(#trajet-road)"><path d="M14 6.5L19.6 14.4L21.6 12.6L30.5 27H1.5Z" fill="#2B4C70"/><path d="M14 6.5L19.6 14.4L21.6 12.6L30.5 27H17.5Z" fill="#739BBF"/></g>
<path d="M13.25 7V1.4H14.75V7ZM14.6 1.4L19 3.1L14.6 4.8Z" fill="#1E3550"/></svg><span class="brand-name">Trajet</span></a>"""


# Нижнє меню звіту: (ключ, підпис, іконка SVG).
SECTIONS = [
    ("spend", "Витрати", '<circle cx="12" cy="12" r="9"/><path d="M12 3v9h9"/>'),
    ("save", "Відкладено", '<path d="M12 3v12M7 10l5 5 5-5M4 20h16"/>'),
    ("fixed", "Фіксовані", '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>'),
    ("limits", "Ліміти", '<path d="M4 18a8 8 0 1 1 16 0"/><path d="M12 18l4-6"/>'),
]


def render(ledger=LEDGER, *, head="", nav="", flash="", viewer=None, limits=None, settings_url="", splash=False):
    """Повна HTML-сторінка звіту. head/nav/flash/viewer/settings_url — додатки від веб-застосунку."""
    d = load(ledger, viewer)
    limit_table = load_limits(limits)
    other = next(p for p in PEOPLE if p != viewer) if viewer else None
    keys = d["keys"]
    default = next((k for k in reversed(keys) if "закінчено" in month_caption(d, k)), keys[-1])
    month_id = lambda k: f"{k[0]}-{k[1]:02d}"
    view_tabs = "".join(
        f'<button role="tab" data-p="{v}" aria-selected="{str(v == "Разом").lower()}">{v}</button>' for v in VIEWS
    )
    month_tabs, panels = [], []
    for k in keys:
        partial = "неповний" in month_caption(d, k)
        month_tabs.append(
            f'<button role="tab" data-m="{month_id(k)}" aria-selected="{str(k == default).lower()}">'
            f'{MONTH_NAMES[k[1]]}</button>'
        )
        for v in VIEWS:
            rows = limit_rows(d, k, v, viewer, limit_table)
            panels.append(
                f'<div class="month" data-m="{month_id(k)}" data-p="{v}" hidden>{limits_banner(rows)}'
                f'<div data-s="spend">{block_categories(d, k, v, partial)}{block_cash(d, k, v)}</div>'
                f'<div data-s="save" hidden>{block_savings(d, k, v, partial, v == other)}</div>'
                f'<div data-s="fixed" hidden>{block_fixed(d, k, v)}</div>'
                f'<div data-s="limits" hidden>{block_limits(rows, v, viewer, settings_url, d["last_day"][k] if partial else None)}</div></div>'
            )
    flash_html = f'<p class="flash" role="status">{flash}</p>' if flash else ""
    return f"""<!doctype html>
<html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Trajet</title>{head}
<style>{CSS}</style></head><body>{SPLASH if splash else ""}<main>
<header><h1>{BRAND}</h1>{nav}</header>
{flash_html}
<div class="sticky"><div class="tabs" role="tablist" id="people">{view_tabs}</div>
<div class="tabs" role="tablist" id="months">{''.join(month_tabs)}</div></div>
{''.join(panels)}
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
  if (p + m !== shown) {{ shown = p + m; document.querySelectorAll('.spend').forEach(c => slide(c, 0, false)); }}  // новий місяць чи людина — знову слайд 1
  try {{ localStorage.setItem('view', JSON.stringify({{p, m}})); }} catch (e) {{}}
}}
// Картка витрат: свайп (scroll-snap), точки, кнопка «Діаграма / Список» і стрілки клавіатури.
let shown = '', hint = true;
try {{ hint = !localStorage.getItem('swiped'); }} catch (e) {{}}
const at = c => Math.round(c.querySelector('.slides').scrollLeft / (c.querySelector('.slides').clientWidth || 1));
function slide(c, i, smooth = true) {{
  const x = c.querySelector('.slides');
  x.scrollTo({{ left: i * x.clientWidth, behavior: smooth && !matchMedia('(prefers-reduced-motion: reduce)').matches ? 'smooth' : 'auto' }});
  sync(c, i);
}}
function sync(c, i = at(c)) {{
  c.querySelectorAll('.dots button').forEach((b, k) => b.setAttribute('aria-current', k === i));
  c.querySelector('.slidetoggle').textContent = i ? 'Список' : 'Діаграма';
  if (i && hint) {{ hint = false; try {{ localStorage.setItem('swiped', '1'); }} catch (e) {{}} }}
  document.querySelectorAll('.swipehint').forEach(h => h.hidden = !hint);
}}
document.querySelectorAll('.spend').forEach(c => {{
  const x = c.querySelector('.slides');
  x.addEventListener('scroll', () => sync(c), {{ passive: true }});
  c.querySelectorAll('.dots button').forEach((b, k) => b.addEventListener('click', () => slide(c, k)));
  c.querySelector('.slidetoggle').addEventListener('click', () => slide(c, at(c) ? 0 : 1));
  x.addEventListener('keydown', e => {{ if (e.key === 'ArrowRight') slide(c, 1); if (e.key === 'ArrowLeft') slide(c, 0); }});
}});
pt.forEach(t => t.addEventListener('click', () => {{ p = t.dataset.p; show(); }}));
st.forEach(t => t.addEventListener('click', () => {{ s = t.dataset.s; show(); scrollTo(0, 0); }}));
// Меню в шапці закривається дотиком будь-де поза ним.
document.addEventListener('click', e => document.querySelectorAll('details.menu[open]').forEach(x => x.contains(e.target) || x.removeAttribute('open')));
mt.forEach(t => t.addEventListener('click', () => {{ m = t.dataset.m; show(); }}));
if (document.querySelector('.flash')) navigator.vibrate?.(10);  // відгук після збереження готівки
document.querySelectorAll('.alert').forEach(a => a.addEventListener('click', () => {{ s = 'limits'; show(); scrollTo(0, 0); }}));
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
