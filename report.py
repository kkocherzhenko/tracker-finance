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

from ui_strings import MONTH_LOC, say

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
    return f'<span class="num" data-n="{x:.{decimals}f}">{zl(x, decimals)[:-3]}</span><span class="cur">зл</span>'


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


def hero_sentence(d, key, view, rows, partial):
    """Одне людське речення під сумою: на що пішло найбільше і як проти минулого місяця."""
    parts = [say("top", category=rows[0][0], amount=zl(rows[0][1], 0))]
    if partial:
        last = d["last_day"][key]
        parts.insert(0, say("partial", day=f"{last.day} {MONTH_GEN[last.month]}"))
    else:
        i = d["keys"].index(key)
        prev = sum(d["categories"].get((d["keys"][i - 1], view), {}).values()) if i else 0
        total = sum(v for _, v in rows)
        if prev > 0 and total != prev:
            parts.append(say("more" if total > prev else "less", pct=pct(abs(total - prev), prev), month=MONTH_LOC[d["keys"][i - 1][1]]))
    return " ".join(parts)


def block_categories(d, key, view, partial):
    rows = sorted(d["categories"][key, view].items(), key=lambda kv: -kv[1])
    if not rows:
        return empty("Куди йдуть гроші", say("empty_spend"))
    total = sum(v for _, v in rows)
    top = rows[0][1] or Decimal(1)
    # Смуга лише в трьох найбільших; решта — звичайний рядок. Колір точки збігається з кільцем на слайді 2.
    items = "".join(
        f'<li class="cat{" top" if i < 3 else ""}{" faded" if i >= 8 else ""}" style="--c:var(--cat{i % 8 + 1})">'
        f'<span class="dot"></span><span class="name">{escape(n)}</span><span class="share">{pct(v, total)}</span>'
        f'<span class="val">{zl(v, 0)}</span>'
        + (f'<span class="track"><span class="bar" style="width:{max(v, 0) / top * 100:.1f}%"></span></span>' if i < 3 else "")
        + "</li>"
        for i, (n, v) in enumerate(rows)
    )
    table = "".join(
        f"<tr><td>{escape(n)}</td><td>{zl(v)}</td><td>{pct(v, total)}</td></tr>" for n, v in rows
    )
    legend = "".join(
        f'<li class="{"faded" if i >= 8 else ""}" style="--c:var(--cat{i % 8 + 1})"><span class="dot"></span>{escape(n)} <b>{pct(v, total)}</b></li>'
        for i, (n, v) in enumerate(rows)
    )
    # Два слайди (scroll-snap): 1 — сума і список, 2 — кільце із сумою в центрі. Сума видна один раз.
    return f"""
<section class="sec spend"><div class="sechead"><h2>Куди йдуть гроші</h2><button type="button" class="slidetoggle">Діаграма</button></div>
<div class="slides" tabindex="0" aria-label="Витрати: список і діаграма, стрілки вліво і вправо перемикають">
<div class="slide"><div class="hero">{zl_html(total)}</div><p class="lede">{hero_sentence(d, key, view, rows, partial)}</p>
<ul class="cats">{items}</ul>
<details><summary>Показати таблицею</summary>
<table><tr><th>Категорія</th><th>Сума</th><th>Частка</th></tr>{table}</table></details></div>
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
        return empty("Скільки відкладено", say("private_money", view=view))
    s = d["savings"][key, view]
    income, spent, saved = s["income"], s["spent"], s["saved"]
    if not income:
        return empty("Скільки відкладено", say("no_income"))
    lede = say("saved", saved=zl(saved, 0), income=zl(income, 0)) + (" " + say("saved_partial") if partial else "")
    return f"""
<section class="card"><h2>Скільки відкладено</h2>
{ring(saved / income * 100, pct(saved, income), saved < 0)}<p class="lede">{lede}</p></section>"""


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
<section class="sec"><h2>Фіксовані й змінні</h2>
<div class="hero mid">{pct(fixed, total)}</div><p class="lede">Стільки витрат — фіксовані: {zl(fixed, 0)} з {zl(total, 0)}. {say("managed", managed=zl(managed))}</p>
{stacked([("Змінні", managed, "a"), ("Фіксовані", fixed, "b")])}{by_person}</section>"""


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
    """Смуга на всю ширину: одна конкретна фраза і плашки; дотик відкриває вкладку «Ліміти»."""
    hot = [(n, sp, l) for n, sp, l in rows if level(sp, l)[0] != "fine"]
    if not hot:
        return ""
    def phrase(n, sp, l):
        return say("over", category=n, over=zl(sp - l, 0)) if sp > l else say("near", category=n, left=zl(l - sp, 0))
    title = phrase(*hot[0]) if len(hot) == 1 else say("several")
    chips = "".join(
        f'<span class="achip {level(sp, l)[0]}">{escape(n)} <b>{f"+{zl(sp - l, 0)}" if sp > l else pct(sp, l)}</b></span>'
        for n, sp, l in hot
    ) if len(hot) > 1 else ""
    return (f'<div class="band alert" role="alert"><button type="button" class="atitle">{escape(title)} <span aria-hidden="true">›</span></button>'
            + (f'<div class="achips">{chips}</div>' if chips else "") + "</div>")


STATE = {"fine": "В нормі", "near": "Близько", "over": "Перевищено"}
# Мала гора з пунктирною тропою і прапорцем — спрощений знак trajet-zigzag з logo/.
PEAK = ('<svg class="peak" viewBox="0 0 64 48" aria-hidden="true"><path class="hill" d="M2 46 L30 6 L38 14 L62 46 Z"/>'
        '<path class="path" d="M14 44 C24 40 34 38 26 32 S 22 22 30 18 S 34 10 30 8"/><circle cx="14" cy="44" r="2.5"/>'
        '<path class="flag" d="M30 8 V1 l6 2.2 -6 2.2"/></svg>')


def empty(title, text, action=""):
    """Порожній або приватний стан: гірка з тропою, одне речення і дія, якщо є."""
    return f'<section class="sec empty"><h2>{title}</h2><div class="emptybody">{PEAK}<div><p>{text}</p>{action}</div></div></section>'


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


def block_limits(rows, view, viewer, settings_url, last=None):
    """last — остання дата даних неповного місяця: тоді показуємо позначку «сьогодні» і скільки можна на день."""
    if viewer and view not in ("Разом", viewer):
        return empty("Ліміти", say("private_limits", view=view))
    if not rows:
        action = f'<a class="btn" href="{settings_url}">Задати ліміт</a>' if settings_url else ""
        return empty("Ліміти", say("empty_limits"), action)
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
    return f'<section class="sec"><h2>Ліміти на місяць</h2>{"".join(items)}{link}</section>'


def block_cash(d, key, view):
    rows = d["cash"][key, view]
    if not rows:
        return ""
    items = "".join(
        f"<li><span>{escape(r['narration'])}<small>{r['date'].day} {MONTH_GEN[r['date'].month]} · "
        f"{escape(category_name(r['category']))} · {escape(r['person'])}</small></span><b>{zl(r['number'])}</b></li>"
        for r in rows
    )
    return f'<section class="sec"><h2>Готівка з телефону</h2><ul class="cash">{items}</ul></section>'


# Шрифти лежать у static/fonts (OFL, з fontsource), шлях відносний — працює і в застосунку, і в report.html.
# Браузер вантажить лише ті набори символів, що є на сторінці (unicode-range): кирилицю і латиницю.
FONT_RANGES = {
    "cyrillic": "U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116",
    "latin-ext": "U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF",
    "latin": "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD",
}
FONT_CSS = "".join(
    f"@font-face {{ font-family:{family}; font-weight:{weight}; font-display:swap; unicode-range:{ranges}; "
    f"src:url(static/fonts/{family.lower()}-{subset}-{weight}-normal.woff2) format('woff2'); }}\n"
    for family, weight in (("Onest", 400), ("Onest", 600), ("Literata", 300), ("Literata", 600))
    for subset, ranges in FONT_RANGES.items()
)
FONT_PRELOAD = "".join(
    f'<link rel="preload" href="static/fonts/{f}-cyrillic-{w}-normal.woff2" as="font" type="font/woff2" crossorigin>'
    for f, w in (("onest", 400), ("literata", 300))
)

CSS = FONT_CSS + """
/* Trajet: тепла біла основа, один акцент, тонкі лінії замість карток. Кольори — палітра логотипа (logo/palette-prompt-en.md).
   Лише 3 радіуси (--r-s/--r-m/--r-full), 1 тінь (--lift), 3 кольори тексту (--text, --text-muted, --on-accent). */
:root {
  --bg:#e9eff3; --surface:#fff; --border:#d0dced; --text:#1e3550;
  --text-muted:#4f6277; /* у палітрі #53677D; на 2% темніше, щоб на тлі полів (--border) був контраст 4.5:1 */
  --accent:#739bbf; --accent-strong:#2b4c70; --on-accent:#fff;
  --positive:#2f7a59; --negative:#c2534b; --warning:#946a1e;
  --cat1:#1e3550; --cat2:#739bbf; --cat3:#a9c1da; --cat4:#4a6f94; --cat5:#d0dced; --cat6:#2b4c70; --cat7:#8fb0cf; --cat8:#53677d;
  --base:color-mix(in srgb, var(--surface) 96%, var(--warning)); /* тепла біла основа */
  --ice:var(--bg); /* крижане тло — лише для однієї картки і смуги на всю ширину */
  --soft:color-mix(in srgb, var(--border) 50%, var(--base));
  --r-s:8px; --r-m:16px; --r-full:999px;
  --lift:0 6px 20px color-mix(in srgb, var(--text) 18%, transparent);
  --font-text:Onest, -apple-system, system-ui, sans-serif; --font-display:Literata, Georgia, serif;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--base); color:var(--text); font:400 16px/1.5 var(--font-text); -webkit-font-smoothing:antialiased; font-variant-numeric:tabular-nums; }
main { max-width:720px; margin:0 auto; padding:0 24px calc(120px + env(safe-area-inset-bottom, 0px)); padding-top:env(safe-area-inset-top, 0); }
header { display:flex; align-items:center; gap:12px; padding:18px 0 8px; }
h1, h2, .hero, .ring b, .donut b { font-family:var(--font-display); font-variant-numeric:lining-nums tabular-nums; }
h1 { margin:0; flex:1; font-size:1.35rem; font-weight:600; letter-spacing:-.01em; }
h2 { margin:0 0 12px; font-size:1.2rem; font-weight:600; }
b, strong, th { font-weight:600; }
a { color:var(--text); text-decoration-color:var(--accent); text-decoration-thickness:2px; text-underline-offset:4px; }
small { color:var(--text-muted); }
:focus-visible { outline:2px solid var(--accent-strong); outline-offset:2px; }
.nav { display:flex; gap:8px; align-items:center; }
.btn { display:inline-flex; align-items:center; justify-content:center; min-height:48px; padding:0 22px; border:0; border-radius:var(--r-full); background:var(--accent-strong); color:var(--on-accent); font:600 1rem var(--font-text); text-decoration:none; cursor:pointer; }
.btn.ghost { min-height:44px; background:none; color:var(--text); border:1px solid var(--text-muted); }

/* Перемикачі: люди — сегменти, місяці — горизонтальна стрічка */
.sticky { position:sticky; top:0; z-index:1; background:var(--base); padding:8px 0 0; }
.tabs { display:flex; }
#people { padding:4px; border-radius:var(--r-full); background:var(--soft); }
#people button { flex:1; min-height:44px; border:0; border-radius:var(--r-full); background:none; color:var(--text); font:inherit; cursor:pointer; }
#people button[aria-selected="true"] { background:var(--accent-strong); color:var(--on-accent); font-weight:600; }
#months { gap:4px; margin:6px -24px 0; padding:0 24px; overflow-x:auto; scrollbar-width:none; border-bottom:1px solid var(--border); }
#months::-webkit-scrollbar { display:none; }
#months button { flex:none; min-height:44px; padding:0 12px; border:0; border-bottom:2px solid transparent; background:none; color:var(--text-muted); font:inherit; cursor:pointer; }
#months button[aria-selected="true"] { color:var(--text); font-weight:600; border-bottom-color:var(--text); }
.caption { margin:14px 0 0; color:var(--text-muted); font-size:.9rem; }

/* Розділи: звичайні блоки з тонкою лінією; залита лише .card, на всю ширину — лише .band */
.sec { padding:24px 0 8px; }
/* Роздільник — тропа з логотипа (точка, серпантин, прапорець), далі тонка лінія. Маска, щоб колір був зі змінної. */
.sec + .sec::before { content:""; display:block; height:16px; margin-bottom:20px; background:var(--accent);
  -webkit-mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 96 16'%3E%3Ccircle cx='3' cy='12' r='2.5'/%3E%3Cpath d='M3 12 C15 12 18 4 30 4 S46 12 58 12 S74 5 84 5' fill='none' stroke='%23000' stroke-width='1.6' stroke-dasharray='3 3' stroke-linecap='round'/%3E%3Cpath d='M86 14 V2 l7 2.4 -7 2.4'/%3E%3C/svg%3E") 0 50% / 96px 16px no-repeat, linear-gradient(#000, #000) 104px 50% / calc(100% - 104px) 1px no-repeat;
  mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 96 16'%3E%3Ccircle cx='3' cy='12' r='2.5'/%3E%3Cpath d='M3 12 C15 12 18 4 30 4 S46 12 58 12 S74 5 84 5' fill='none' stroke='%23000' stroke-width='1.6' stroke-dasharray='3 3' stroke-linecap='round'/%3E%3Cpath d='M86 14 V2 l7 2.4 -7 2.4'/%3E%3C/svg%3E") 0 50% / 96px 16px no-repeat, linear-gradient(#000, #000) 104px 50% / calc(100% - 104px) 1px no-repeat; }
.sec + .sec { padding-top:16px; }
.sechead { display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:4px; } .sechead h2 { margin:0; }
.card { margin:24px 0; padding:20px; border-radius:var(--r-m); background:var(--ice); }
.band { margin:12px -24px 0; padding:12px 24px 14px; background:var(--ice); cursor:pointer; }
.hero { margin:8px 0 0; font-size:4.5rem; line-height:1; font-weight:300; letter-spacing:-.035em; }
.hero.mid { font-size:3rem; }
.cur { margin-left:.12em; font:400 .32em var(--font-text); color:var(--text-muted); letter-spacing:0; }
.lede { margin:10px 0 0; max-width:32ch; color:var(--text-muted); }

/* Категорії: точка, назва, частка, сума; смуга лише в трьох найбільших */
.cats { list-style:none; margin:20px 0 0; padding:0; }
.cat { display:grid; grid-template-columns:auto 1fr auto 5.5em; align-items:baseline; column-gap:10px; padding:10px 0; border-top:1px solid var(--border); }
.cat:first-child { border-top:0; }
.dot { display:inline-block; width:8px; height:8px; border-radius:var(--r-full); background:var(--c, var(--accent)); }
.faded .dot { opacity:.6; } /* понад 8 категорій — ті самі кольори, але прозоріші */
.cat .dot { align-self:center; }
.cat .name { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.share { color:var(--text-muted); font-size:.85rem; }
.val { text-align:right; white-space:nowrap; } .cat.top .val { font-weight:600; }
.track { grid-column:2 / -1; display:block; height:4px; margin-top:8px; border-radius:var(--r-full); background:var(--soft); overflow:hidden; }
.bar { display:block; height:100%; border-radius:var(--r-full); background:var(--c, var(--accent)); transform-origin:left; animation:grow .4s ease-out; }

/* Слайди «список / діаграма» */
.slidetoggle { min-height:44px; padding:0 2px; border:0; background:none; color:var(--text); font:inherit; text-decoration:underline; text-decoration-color:var(--accent); text-decoration-thickness:2px; text-underline-offset:4px; cursor:pointer; }
.slides { display:flex; overflow-x:auto; scroll-snap-type:x mandatory; overscroll-behavior-x:contain; scrollbar-width:none; }
.slides::-webkit-scrollbar { display:none; } .slides:focus-visible { border-radius:var(--r-s); }
.slide { flex:0 0 100%; min-width:0; scroll-snap-align:start; scroll-snap-stop:always; }
.donut { position:relative; width:min(320px, 100%); aspect-ratio:1; margin:16px auto 20px; } /* удвічі від 160 px, але не ширше картки */
.donut svg { display:block; width:100%; height:100%; } .donut circle { fill:none; stroke-width:18; animation:draw .4s ease-out; }
.donut div { position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; }
.donut b { font-size:2.5rem; font-weight:300; letter-spacing:-.03em; } .donut small { font-size:1rem; }
.dlegend { list-style:none; margin:0; padding:0; display:grid; grid-template-columns:1fr 1fr; gap:8px 16px; font-size:.9rem; }
.dlegend li { display:flex; align-items:center; gap:8px; min-width:0; } .dlegend b { margin-left:auto; }
.dots { display:flex; gap:4px; margin:4px 0 0 -14px; }
.dots button { display:grid; place-items:center; width:44px; height:44px; padding:0; border:0; background:none; cursor:pointer; }
.dots button::before { content:""; width:8px; height:8px; border-radius:var(--r-full); background:var(--border); } .dots button[aria-current="true"]::before { background:var(--accent-strong); }
.swipehint { margin:0; color:var(--text-muted); font-size:.85rem; }
details { margin-top:8px; color:var(--text-muted); } summary { cursor:pointer; padding:10px 0; }
table { width:100%; border-collapse:collapse; margin-top:8px; } td, th { padding:10px 4px; border-bottom:1px solid var(--border); text-align:left; vertical-align:top; }
th { font-size:.9rem; color:var(--text-muted); } td:last-child, th:last-child { text-align:right; white-space:nowrap; }

/* Заощадження і фіксовані */
.ring { position:relative; width:150px; height:150px; margin:8px 0; }
.ring svg { width:100%; height:100%; } .ring circle { fill:none; stroke-width:12; } .rtrack { stroke:var(--surface); }
.rarc { stroke:var(--accent-strong); stroke-linecap:round; animation:draw .4s ease-out; } .ring.neg .rarc { stroke:var(--text); }
.ring div { position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; }
.ring b { font-size:2.4rem; font-weight:300; letter-spacing:-.03em; line-height:1; } .ring small { font-size:.85rem; }
.stack { display:flex; gap:2px; height:10px; margin-top:20px; }
.seg { min-width:2px; } .seg:first-child { border-radius:var(--r-full) 0 0 var(--r-full); } .seg:last-child { border-radius:0 var(--r-full) var(--r-full) 0; }
.a { background:var(--cat1); } .b { background:var(--cat2); }
.legend { display:flex; gap:16px; flex-wrap:wrap; margin-top:10px; font-size:.9rem; color:var(--text-muted); }
.sw { display:inline-block; width:8px; height:8px; border-radius:var(--r-full); margin-right:6px; } .legend b { color:var(--text); }

/* Ліміти: червоний / жовтий / зелений — лише тут */
.limit { padding:14px 0; border-top:1px solid var(--border); } .limit:first-of-type { border-top:0; }
.fine { --state:var(--positive); } .near { --state:var(--warning); } .over { --state:var(--negative); }
.lhead { display:flex; justify-content:space-between; align-items:baseline; gap:8px; } .lhead > span:last-child { font-weight:600; white-space:nowrap; }
.lchip { margin-left:6px; color:var(--text-muted); font-size:.85rem; white-space:nowrap; }
.lchip::before { content:""; display:inline-block; width:8px; height:8px; margin-right:5px; border-radius:var(--r-full); background:var(--state); }
.climb { display:block; width:100%; height:auto; margin:6px 0 2px; overflow:visible; }
.climb .hill { fill:var(--soft); } .climb polyline { fill:none; stroke-width:3; stroke-linecap:round; stroke-linejoin:round; }
.climb .trail { stroke:var(--text-muted); stroke-width:1.5; stroke-dasharray:4 4; } .climb .done { stroke:var(--state); animation:draw .4s ease-out; }
.climb .flag { fill:var(--state); stroke:var(--text); stroke-width:1.2; stroke-linejoin:round; } .climb .now { stroke:var(--text); stroke-width:2; }
.achips { display:flex; gap:8px; margin-top:8px; overflow-x:auto; white-space:nowrap; scrollbar-width:none; } .achips::-webkit-scrollbar { display:none; }
.achip { flex:none; padding:6px 12px; border-radius:var(--r-full); background:var(--base); font-size:.9rem; }
.achip::before { content:""; display:inline-block; width:8px; height:8px; margin-right:6px; border-radius:var(--r-full); background:var(--state); }
.atitle { display:block; width:100%; min-height:44px; padding:0; border:0; background:none; color:var(--text); font:inherit; text-align:left; cursor:pointer; }

/* Порожні стани: гірка з тропою */
.emptybody { display:flex; gap:16px; align-items:flex-start; } .emptybody p { margin:4px 0 12px; max-width:28ch; }
.peak { flex:none; width:64px; height:48px; overflow:visible; }
.peak .hill { fill:var(--ice); } .peak .path { fill:none; stroke:var(--text); stroke-width:1.6; stroke-dasharray:3 3; stroke-linecap:round; }
.peak circle { fill:var(--text); } .peak .flag { fill:var(--accent-strong); stroke:var(--text); stroke-width:1.2; stroke-linejoin:round; }

/* Готівка */
.cash { list-style:none; margin:0; padding:0; }
.cash li { display:flex; justify-content:space-between; align-items:baseline; gap:12px; padding:10px 0; border-top:1px solid var(--border); } .cash li:first-child { border-top:0; }
.cash small { display:block; }

/* Нижнє меню, «+», меню в шапці, повідомлення */
.tabbar { position:fixed; z-index:1; left:0; right:0; bottom:0; display:flex; justify-content:center; padding:0 8px env(safe-area-inset-bottom, 0px); background:var(--surface); border-top:1px solid var(--border); }
.tabbar button { flex:1; max-width:180px; min-height:56px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:2px; border:0; border-top:2px solid transparent; background:none; color:var(--text-muted); font:inherit; font-size:.72rem; cursor:pointer; }
.tabbar button[aria-selected="true"] { color:var(--text); font-weight:600; border-top-color:var(--accent-strong); }
.tabbar svg { width:24px; height:24px; fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }
/* «+» — по центру нижнього меню, над ним; суми праворуч, тож кнопка їх не закриває */
.fab { position:fixed; z-index:2; left:calc(50% - 32px); bottom:calc(18px + env(safe-area-inset-bottom, 0px)); width:64px; height:64px; border-radius:var(--r-full); display:flex; align-items:center; justify-content:center; background:var(--accent-strong); color:var(--on-accent); text-decoration:none; box-shadow:var(--lift); }
.fab svg { width:28px; height:28px; fill:none; stroke:currentColor; stroke-width:2.4; stroke-linecap:round; }
.tabbar.has-fab button:nth-child(2) { margin-right:80px; }
.menu { position:relative; } .menu summary::-webkit-details-marker { display:none; }
.menu summary { list-style:none; display:flex; align-items:center; min-height:44px; padding:0 16px; border:1px solid var(--text-muted); border-radius:var(--r-full); font-weight:600; cursor:pointer; }
.menu-list { position:absolute; right:0; top:calc(100% + 8px); z-index:3; min-width:210px; display:flex; flex-direction:column; padding:6px; background:var(--surface); border-radius:var(--r-m); box-shadow:var(--lift); }
.menu-list a, .menu-list button { display:flex; align-items:center; width:100%; min-height:48px; padding:0 14px; border:0; border-radius:var(--r-s); background:none; color:var(--text); font:inherit; text-align:left; text-decoration:none; cursor:pointer; }
.menu-list a:hover, .menu-list button:hover { background:var(--soft); } .menu-list form { margin:0; }
.flash { display:flex; align-items:center; gap:10px; position:fixed; z-index:3; left:24px; right:24px; bottom:calc(96px + env(safe-area-inset-bottom, 0px)); max-width:672px; margin:0 auto; padding:14px 18px; border-radius:var(--r-m); background:var(--text); color:var(--on-accent); box-shadow:var(--lift); animation:toast 5s forwards; }
.tick { flex:none; width:22px; height:22px; fill:none; stroke:currentColor; stroke-width:2.4; stroke-linecap:round; stroke-linejoin:round; stroke-dasharray:24; animation:tickdraw .4s .1s ease-out backwards; }
@keyframes tickdraw { from { stroke-dashoffset:24; } }
@keyframes toast { 0%, 85% { opacity:1; } 100% { opacity:0; visibility:hidden; } }
.month[hidden] { display:none; }
.foot { color:var(--text-muted); font-size:.85rem; }
.foot a { display:inline-flex; align-items:center; min-height:44px; font-size:1rem; } /* посилання «Налаштувати ліміти» — ціль ≥ 44 px */

/* Рух: розділ з'являється знизу, смуги й кільця ростуть, коли розділ показано; натискання трохи стискає */
.month [data-s]:not([hidden]) { animation:rise .18s ease-out; }
@keyframes rise { from { opacity:0; transform:translateY(6px); } }
@keyframes grow { from { transform:scaleX(0); } }
@keyframes draw { from { stroke-dasharray:0 999; } }
.btn, .tabs button, .fab, .tabbar button, .alert, .slidetoggle { transition:transform .1s ease-out; }
.btn:active, .tabs button:active, .fab:active, .tabbar button:active, .alert:active, .slidetoggle:active { transform:scale(.97); }
@media (prefers-reduced-motion: reduce) { *:not(.flash) { animation:none !important; transition:none !important; } }
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
                f'<p class="caption{" partial" if partial else ""}">{v} · {MONTH_NAMES[k[1]].lower()} {k[0]} · {cap}{note}</p>'
                f'<div data-s="spend">{block_categories(d, k, v, partial)}{block_cash(d, k, v)}</div>'
                f'<div data-s="save" hidden>{block_savings(d, k, v, partial, v == other)}</div>'
                f'<div data-s="fixed" hidden>{block_fixed(d, k, v)}</div>'
                f'<div data-s="limits" hidden>{block_limits(rows, v, viewer, settings_url, d["last_day"][k] if partial else None)}</div></div>'
            )
    tick = '<svg class="tick" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7"/></svg>'
    flash_html = f'<p class="flash" role="status">{tick}{flash}</p>' if flash else ""
    return f"""<!doctype html>
<html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Наші фінанси</title>{FONT_PRELOAD}{head}
<style>{CSS}</style></head><body><main>
<header><h1>Наші фінанси</h1>{nav}</header>
{flash_html}
<div class="sticky"><div class="tabs" role="tablist" id="people">{view_tabs}</div>
<div class="tabs" role="tablist" id="months">{''.join(month_tabs)}</div></div>
{''.join(panels)}
<p class="foot">* місяць ще не закінчився. Дані: виписки Олі й Марка за 1 серпня — 15 жовтня 2026 і готівка, додана з телефону; злоті.</p>
</main>
<nav class="tabbar{" has-fab" if nav else ""}" role="tablist" id="sections">{"".join(
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
// Велика сума один раз «набігає» від нуля (400 мс); без JS чи з «менше руху» — одразу готове число.
if (!matchMedia('(prefers-reduced-motion: reduce)').matches) document.querySelectorAll('.month:not([hidden]) .hero .num').forEach(el => {{
  const end = parseFloat(el.dataset.n), t0 = performance.now(), fmt = v => Math.round(v).toString().replace(/\\B(?=(\\d{{3}})+(?!\\d))/g, ' ');
  const tick = t => {{ const k = Math.min((t - t0) / 400, 1); el.textContent = fmt(end * (1 - (1 - k) ** 3)); if (k < 1) requestAnimationFrame(tick); }};
  requestAnimationFrame(tick);
}});
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
