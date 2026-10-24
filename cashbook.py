"""Готівка з телефону: запис у cash.beancount з перевіркою bean-check і відкатом при помилці."""
import fcntl
from pathlib import Path

from beancount import loader

HEADER = """; Готівкові витрати, додані з телефону (веб-застосунок і форма «+» у Fava).
; Файл не потрапляє в git: на сервері в ньому живі записи, у репозиторії — нічого.
; Нові записи Fava вставляє перед цим рядком:
2026-07-31 custom "fava-option" "insert-entry" ".*"
"""


def ensure(path):
    """main.beancount підключає cash.beancount, тому файл має існувати навіть порожнім."""
    path = Path(path)
    if not path.exists():
        path.write_text(HEADER, encoding="utf-8")


def text(entry):
    return (
        f'\n{entry["date"]} * "{entry["description"]}" #cash{" #shared" if entry["shared"] else ""}\n'
        f'  added_by: "{entry["user"]}"\n'
        f'  {entry["account"]}  {entry["amount"]:.2f} PLN\n'
        f'  Assets:{entry["person"]}:Готівка\n'
    )


def append(cash_path, ledger_path, entry):
    """Дописує запис і перевіряє весь облік. Якщо bean-check бачить помилку, повертає файл як був."""
    cash_path = Path(cash_path)
    ensure(cash_path)
    with open(cash_path, "r+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        before = f.read()
        f.write(text(entry))
        f.flush()
        _, errors, _ = loader.load_file(str(ledger_path))
        if errors:
            f.seek(0)
            f.truncate()
            f.write(before)
            raise ValueError(f"Запис не пройшов перевірку обліку: {errors[0].message}")
