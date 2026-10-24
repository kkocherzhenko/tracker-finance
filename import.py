"""Збирає transactions.beancount з обох виписок у data/ за правилами з rules.csv і rules-marko.csv.

Виписка Олі (data/statement.csv) — CSV банку типу Revolut, через кому, найстаріші рядки зверху.
Виписка Марка (data/marko-statement.csv) — польський банк: шапка з 6 рядків, крапка з комою,
дати 31.08.2026, суми «1 234,56», найновіші рядки зверху.
"""
import csv
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import cashbook

ROOT = Path(__file__).parent

def load_rules(name):
    return list(csv.DictReader(open(ROOT / name, encoding="utf-8")))


def find_rule(rules, description):
    text = description.lower()
    return next((r for r in rules if r["шаблон"].lower() in text), None)


def polish_number(text):
    """«-1 234,56» -> Decimal("-1234.56")."""
    return Decimal(text.replace("\xa0", "").replace(" ", "").replace(",", "."))


def read_olia(path):
    """Рядки в порядку банку (найстаріші зверху): (дата, опис, сума, залишок)."""
    for r in csv.DictReader(open(path, encoding="utf-8")):
        if r["State"] != "COMPLETED":
            continue
        yield r["Completed Date"][:10], r["Description"], Decimal(r["Amount"]), Decimal(r["Balance"])


def read_marko(path):
    """Шапку до рядка «Data operacji» пропускаємо. Банк пише найновіші рядки зверху,
    і залишок рахується саме в цьому порядку, тому просто розвертаємо список, не сортуючи."""
    lines = open(path, encoding="utf-8").read().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("Data operacji;"))
    rows = []
    for r in csv.DictReader(lines[start:], delimiter=";"):
        day = datetime.strptime(r["Data operacji"], "%d.%m.%Y").date().isoformat()
        rows.append((day, r["Opis"], polish_number(r["Kwota"]), polish_number(r["Saldo po operacji"])))
    return reversed(rows)


# Хто, яка виписка, як її читати, рахунок банку, правила, початковий залишок на 31.07.2026.
PEOPLE = [
    ("Оля", "statement.csv", read_olia, "Assets:Оля:Банк", "rules.csv", Decimal("4500.00")),
    ("Марко", "marko-statement.csv", read_marko, "Assets:Марко:Банк", "rules-marko.csv", Decimal("2860.40")),
]

lines = []
errors = 0
for person, filename, reader, bank, rules_file, opening in PEOPLE:
    rules = load_rules(rules_file)
    no_category = f"Expenses:{person}:Без-Категорії"
    other_income = f"Income:{person}:Інше"

    # Однаковий рядок (дата, опис, сума, залишок) рахуємо один раз.
    seen = set()
    rows = []
    for row in reader(ROOT / "data" / filename):
        if row not in seen:
            seen.add(row)
            rows.append(row)

    lines.append(f"; ===== {person}: data/{filename}, операцій: {len(rows)} =====\n")
    prev_balance = opening
    for day, description, amount, balance in rows:
        if prev_balance + amount != balance:
            print(f"Залишок не сходиться ({person}): {day} {description}", file=sys.stderr)
            errors += 1
        prev_balance = balance

        rule = find_rule(rules, description)
        if rule:
            account = rule["рахунок"]
        else:
            account = other_income if amount > 0 else no_category
        tag = " #fixed" if rule and rule["фіксована"] == "так" else ""
        # #shared бачать обоє; усе без нього — особисте, і друга людина його не бачить.
        tag += " #shared" if rule and rule["спільна"] == "так" else ""
        narration = description.replace('"', "'")
        lines.append(
            f'{day} * "{narration}"{tag}\n'
            f"  {bank}  {amount:.2f} PLN\n"
            f"  {account}\n"
        )

    # Звірка з банком для bean-check: залишок після останньої операції місяця (в порядку банку)
    # стверджуємо на перше число наступного місяця, а для останнього місяця — на день після
    # останньої операції.
    month_end = {}
    for day, _, _, balance in rows:
        month_end[day[:7]] = (day, balance)
    for month, (day, bal) in month_end.items():
        y, m = int(month[:4]), int(month[5:])
        check_day = date(y + m // 12, m % 12 + 1, 1)
        if month == rows[-1][0][:7]:
            check_day = date.fromisoformat(day) + timedelta(days=1)
        lines.append(f"{check_day} balance {bank}  {bal:.2f} PLN\n")
    print(f"{person}: записано операцій {len(rows)}, кінцевий залишок {prev_balance:.2f} PLN")

(ROOT / "transactions.beancount").write_text("\n".join(lines), encoding="utf-8")
# Готівку з телефону веб-застосунок пише в cash.beancount (не в git); main.beancount його підключає.
cashbook.ensure(ROOT / "cash.beancount")
sys.exit(1 if errors else 0)
