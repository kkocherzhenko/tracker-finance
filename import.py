"""Збирає transactions.beancount з усіх CSV у data/ за правилами з rules.csv."""
import csv
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parent
BANK = "Assets:Банк"
NO_CATEGORY = "Expenses:Без-Категорії"
OTHER_INCOME = "Income:Інше"

rules = list(csv.DictReader(open(ROOT / "rules.csv", encoding="utf-8")))


def find_rule(description):
    text = description.lower()
    return next((r for r in rules if r["шаблон"].lower() in text), None)


# Однаковий рядок (дата завершення, опис, сума, залишок) з кількох виписок рахуємо один раз.
# Порядок рядків лишається таким, як у банку: залишок рахується саме в ньому.
seen = set()
rows = []
for path in sorted((ROOT / "data").glob("*.csv")):
    for r in csv.DictReader(open(path, encoding="utf-8")):
        if r["State"] != "COMPLETED":
            continue
        key = (r["Completed Date"], r["Description"], r["Amount"], r["Balance"])
        if key not in seen:
            seen.add(key)
            rows.append(r)

lines = []
prev_balance = None
errors = 0
for r in rows:
    amount = Decimal(r["Amount"])
    balance = Decimal(r["Balance"])
    if prev_balance is not None and prev_balance + amount != balance:
        print(f"Залишок не сходиться: {r['Completed Date']} {r['Description']}", file=sys.stderr)
        errors += 1
    prev_balance = balance

    rule = find_rule(r["Description"])
    if rule:
        account = rule["рахунок"]
    else:
        account = OTHER_INCOME if amount > 0 else NO_CATEGORY
    tag = " #fixed" if rule and rule["фіксована"] == "так" else ""
    narration = r["Description"].replace('"', "'")
    lines.append(
        f'{r["Completed Date"][:10]} * "{narration}"{tag}\n'
        f"  {BANK}  {amount:.2f} PLN\n"
        f"  {account}\n"
    )

# Звірка з банком для bean-check: залишок з колонки Balance після останньої операції місяця
# (в порядку банку) стверджуємо на перше число наступного місяця, а для останнього місяця —
# на день після останньої операції.
month_end = {}
for r in rows:
    month_end[r["Completed Date"][:7]] = (r["Completed Date"][:10], r["Balance"])
for month, (day, bal) in month_end.items():
    y, m = int(month[:4]), int(month[5:])
    check_day = date(y + m // 12, m % 12 + 1, 1)
    if month == rows[-1]["Completed Date"][:7]:
        check_day = date.fromisoformat(day) + timedelta(days=1)
    lines.append(f"{check_day} balance {BANK}  {Decimal(bal):.2f} PLN\n")

(ROOT / "transactions.beancount").write_text("\n".join(lines), encoding="utf-8")
print(f"Записано операцій: {len(rows)}, кінцевий залишок: {prev_balance:.2f} PLN")
sys.exit(1 if errors else 0)
