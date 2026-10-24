"""Готівка з телефону: запис, зміна і видалення в cash.beancount з перевіркою bean-check і відкатом при помилці."""
import fcntl
import hashlib
import re
from decimal import Decimal
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


# Запис, який пише text(): записи у файлі розділені порожнім рядком.
ENTRY = re.compile(r'(\d{4}-\d{2}-\d{2}) \* "(.*)" #cash( #shared)?\n  added_by: "(.*)"\n  (\S+)  (-?[\d.]+) PLN\n  Assets:([^:\s]+):Готівка')


def entry_id(block):
    """Відбиток тексту запису: якщо запис тим часом змінили, відбиток інший і зміна не пройде."""
    return hashlib.sha1(block.strip().encode()).hexdigest()[:12]


def entries(cash_path):
    """Записи застосунку: [{id, date, description, shared, user, account, amount, person}]."""
    path = Path(cash_path)
    if not path.exists():
        return []
    out = []
    for block in path.read_text(encoding="utf-8").split("\n\n"):
        m = ENTRY.fullmatch(block.strip())
        if m:
            day, description, shared, user, account, amount, person = m.groups()
            out.append({"id": entry_id(block), "date": day, "description": description, "shared": bool(shared),
                        "user": user, "account": account, "amount": Decimal(amount), "person": person})
    return out


def _rewrite(cash_path, ledger_path, eid, entry=None):
    """Замінює запис eid на entry (або видаляє, якщо entry немає) і перевіряє облік; при помилці — файл як був."""
    with open(cash_path, "r+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        before = f.read()
        parts = before.split("\n\n")
        i = next((i for i, b in enumerate(parts) if ENTRY.fullmatch(b.strip()) and entry_id(b) == eid), None)
        if i is None:
            raise ValueError("Цей запис уже змінили або видалили. Оновіть сторінку.")
        if entry is None:
            del parts[i]
        else:
            parts[i] = text(entry).strip("\n") + parts[i][len(parts[i].rstrip("\n")):]
        after = "\n\n".join(parts)
        f.seek(0)
        f.truncate()
        f.write(after if after.endswith("\n") else after + "\n")
        f.flush()
        _, errors, _ = loader.load_file(str(ledger_path))
        if errors:
            f.seek(0)
            f.truncate()
            f.write(before)
            raise ValueError(f"Зміна не пройшла перевірку обліку: {errors[0].message}")


def replace(cash_path, ledger_path, eid, entry):
    _rewrite(cash_path, ledger_path, eid, entry)


def remove(cash_path, ledger_path, eid):
    _rewrite(cash_path, ledger_path, eid)
