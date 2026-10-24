"""Створює файл .env із секретним ключем і хешами паролів: `uv run python make_env.py`.

Запускати на сервері (або локально для перевірки). Паролі вводяться з клавіатури і ніде не
зберігаються у відкритому вигляді: у .env потрапляє лише хеш. Файл .env не потрапляє в git.
"""
import getpass
import secrets
from pathlib import Path

from werkzeug.security import generate_password_hash

ENV = Path(__file__).parent / ".env"

LOGINS = {"olia": "Оля", "marko": "Марко"}  # як у app.py

lines = [f"SECRET_KEY={secrets.token_hex(32)}"]
for login, person in LOGINS.items():
    while True:
        password = getpass.getpass(f"Пароль для {person} (логін {login}, не видно під час вводу): ")
        if len(password) < 8:
            print("Пароль має бути щонайменше 8 символів.")
        elif getpass.getpass("Ще раз: ") != password:
            print("Паролі не збігаються.")
        else:
            break
    lines.append(f"TRACKER_HASH_{login.upper()}={generate_password_hash(password)}")

ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
ENV.chmod(0o600)
print(f"Записано {ENV}. Логіни: {', '.join(LOGINS)}. Перезапустіть веб-застосунок.")
