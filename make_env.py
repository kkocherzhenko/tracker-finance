"""Створює файл .env із секретним ключем і хешами паролів: `uv run python make_env.py`.

Запускати на сервері (або локально для перевірки). Паролі вводяться з клавіатури і ніде не
зберігаються у відкритому вигляді: у .env потрапляє лише хеш. Файл .env не потрапляє в git.
"""
import getpass
import secrets
from pathlib import Path

from werkzeug.security import generate_password_hash

ENV = Path(__file__).parent / ".env"

print("Логіни і паролі для входу. Порожній логін — завершити.")
users = []
while True:
    login = input("Логін: ").strip()
    if not login:
        break
    if ":" in login or "," in login:
        print("Логін не може містити «:» або «,».")
        continue
    password = getpass.getpass("Пароль (не видно під час вводу): ")
    if len(password) < 8:
        print("Пароль має бути щонайменше 8 символів.")
        continue
    if getpass.getpass("Ще раз: ") != password:
        print("Паролі не збігаються.")
        continue
    users.append(f"{login}:{generate_password_hash(password)}")

if not users:
    raise SystemExit("Не додано жодного логіна, .env не змінено.")

ENV.write_text(f"SECRET_KEY={secrets.token_hex(32)}\nTRACKER_USERS={','.join(users)}\n", encoding="utf-8")
ENV.chmod(0o600)
print(f"Записано {ENV} ({len(users)} логін(и)). Перезапустіть веб-застосунок.")
