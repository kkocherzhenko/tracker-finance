"""Готівка з телефону: запис, зміна, видалення й відновлення в cash.beancount.

Кожна зміна: блокування, атомарний запис (тимчасовий файл + перейменування), bean-check усього обліку
і відкат, якщо перевірка не пройшла. Змінювати й видаляти можна лише записи з форми (мають phone_id або
added_by); банківські операції лежать у transactions.beancount, і цей модуль їх не чіпає.
"""
import fcntl
import hashlib
import os
import re
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from beancount import loader

HEADER = """; Готівкові витрати, додані з телефону (веб-застосунок і форма «+» у Fava).
; Файл не потрапляє в git: на сервері в ньому живі записи, у репозиторії — нічого.
; Нові записи Fava вставляє перед цим рядком:
2026-07-31 custom "fava-option" "insert-entry" ".*"
"""

# Запис, який пише text(): записи у файлі розділені порожнім рядком. phone_id немає лише в старих записах.
ENTRY = re.compile(r'(\d{4}-\d{2}-\d{2}) \* "(.*)" #cash( #shared)?\n(?:  phone_id: "([0-9a-f]+)"\n)?'
                   r'  added_by: "(.*)"\n  (\S+)  (-?[\d.]+) PLN\n  Assets:([^:\s]+):Готівка')


def ensure(path):
    """main.beancount підключає cash.beancount, тому файл має існувати навіть порожнім."""
    path = Path(path)
    if not path.exists():
        path.write_text(HEADER, encoding="utf-8")


def text(entry):
    """Текст запису. Лапки й переноси в описі заборонені: інакше опис міг би дописати в облік зайву директиву."""
    if re.search(r'["\\\r\n]', entry["description"]):
        raise ValueError("Опис не може містити лапок і переносів рядка.")
    return (
        f'\n{entry["date"]} * "{entry["description"]}" #cash{" #shared" if entry["shared"] else ""}\n'
        f'  phone_id: "{entry.get("id") or uuid.uuid4().hex[:12]}"\n'
        f'  added_by: "{entry["user"]}"\n'
        f'  {entry["account"]}  {entry["amount"]:.2f} PLN\n'
        f'  Assets:{entry["person"]}:Готівка\n'
    )


def entry_id(block):
    """Сталий номер запису: phone_id, а для старих записів без нього — відбиток тексту."""
    m = ENTRY.fullmatch(block.strip())
    return (m and m.group(4)) or hashlib.sha1(block.strip().encode()).hexdigest()[:12]


def entries(cash_path):
    """Записи застосунку: [{id, date, description, shared, user, account, amount, person, block}]."""
    path = Path(cash_path)
    if not path.exists():
        return []
    out = []
    for block in path.read_text(encoding="utf-8").split("\n\n"):
        m = ENTRY.fullmatch(block.strip())
        if m:
            day, description, shared, _, user, account, amount, person = m.groups()
            out.append({"id": entry_id(block), "date": day, "description": description, "shared": bool(shared),
                        "user": user, "account": account, "amount": Decimal(amount), "person": person,
                        "block": block.strip()})
    return out


@contextmanager
def _locked(cash_path):
    """Окремий файл-замок: сам cash.beancount ми підміняємо перейменуванням, і замок на ньому загубився б."""
    with open(Path(cash_path).with_name(".cash.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _write(path, content):
    """Атомарно: спершу тимчасовий файл, потім перейменування — файл ніколи не буває записаний наполовину."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _change(cash_path, ledger_path, edit):
    """edit(текст файлу) -> новий текст. Пише, перевіряє облік і повертає файл як був, якщо є помилки."""
    cash = Path(cash_path)
    ensure(cash)
    with _locked(cash):
        before = cash.read_text(encoding="utf-8")
        after = edit(before)
        _write(cash, after if after.endswith("\n") else after + "\n")
        _, errors, _ = loader.load_file(str(ledger_path))
        if errors:
            _write(cash, before)
            raise ValueError(f"Запис не пройшов перевірку обліку: {errors[0].message}")


def _blocks_without(content, eid, entry=None):
    """Замінює запис eid на entry (або прибирає його). Помилка, якщо такого запису з форми немає."""
    parts = content.split("\n\n")
    i = next((i for i, b in enumerate(parts) if ENTRY.fullmatch(b.strip()) and entry_id(b) == eid), None)
    if i is None:
        raise ValueError("Цей запис уже змінили або видалили. Оновіть сторінку.")
    if entry is None:
        del parts[i]
    else:
        parts[i] = text(entry).strip("\n") + parts[i][len(parts[i].rstrip("\n")):]
    return "\n\n".join(parts)


def append(cash_path, ledger_path, entry):
    _change(cash_path, ledger_path, lambda content: content + text(entry))


def replace(cash_path, ledger_path, eid, entry):
    _change(cash_path, ledger_path, lambda content: _blocks_without(content, eid, dict(entry, id=eid)))


def remove(cash_path, ledger_path, eid):
    _change(cash_path, ledger_path, lambda content: _blocks_without(content, eid))


def restore(cash_path, ledger_path, block):
    """Повертає видалений запис (для «Скасувати») рівно тим самим текстом."""
    if not ENTRY.fullmatch(block):
        raise ValueError("Цей запис не можна відновити.")
    def add_back(content):
        if any(e["block"] == block for e in entries(cash_path)):
            return content  # уже на місці
        return content.rstrip("\n") + "\n\n" + block + "\n"
    _change(cash_path, ledger_path, add_back)
