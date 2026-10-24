"""Одна команда для перевірки: `uv run python check.py`.

1. Перезбирає transactions.beancount з обох виписок (import.py).
2. Запускає bean-check main.beancount: має мовчати.
3. Друкує змінні витрати Олі й Марка за серпень і вересень і звіряє їх з контрольними цифрами.
"""
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import beanquery

ROOT = Path(__file__).parent
LEDGER = ROOT / "main.beancount"
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

# Контрольні цифри із завдання: змінні витрати (усе, що без тегу #fixed).
EXPECTED = {
    ("Оля", 8): Decimal("2195.21"),
    ("Оля", 9): Decimal("2582.42"),
    ("Марко", 8): Decimal("1855.57"),
    ("Марко", 9): Decimal("2432.83"),
}
MONTHS = {8: "серпень", 9: "вересень"}

print("1. Імпорт виписок")
if subprocess.run([sys.executable, str(ROOT / "import.py")]).returncode:
    sys.exit("Імпорт не вдався: залишок у виписці не сходиться.")

print("\n2. bean-check main.beancount")
bean_check = shutil.which("bean-check") or str(Path(sys.executable).parent / "bean-check")
result = subprocess.run([bean_check, str(LEDGER)], capture_output=True, text=True)
if result.returncode or result.stdout.strip() or result.stderr.strip():
    print(result.stdout + result.stderr)
    sys.exit("bean-check знайшов помилки.")
print("   без повідомлень")

print("\n3. Змінні витрати (без #fixed), PLN")
connection = beanquery.connect(f"beancount:{LEDGER}")
cursor = connection.execute(
    "SELECT leaf(root(account, 2)) AS person, month, sum(number) AS variable "
    "WHERE account ~ '^Expenses:' AND NOT 'fixed' IN tags AND year = 2026 AND month IN (8, 9) "
    "GROUP BY person, month"
)
actual = {(person, month): total for person, month, total in cursor.fetchall()}

ok = True
print(f"   {'хто':<6} {'місяць':<9} {'є':>9} {'має бути':>9}")
for (person, month), expected in EXPECTED.items():
    got = actual.get((person, month), Decimal(0))
    mark = "OK" if got == expected else "НЕ ЗБІГАЄТЬСЯ"
    ok &= got == expected
    print(f"   {person:<6} {MONTHS[month]:<9} {got:>9.2f} {expected:>9.2f}  {mark}")

print("\nУсе збігається." if ok else "\nЄ розбіжності з контрольними цифрами.")
sys.exit(0 if ok else 1)
