"""Точка входу для PythonAnywhere (і будь-якого WSGI-сервера).

Змінні середовища беремо з .env поруч (його створює make_env.py, у git він не потрапляє).
Те, що вже задано в середовищі, .env не перезаписує.
"""
import os
from pathlib import Path

env = Path(__file__).parent / ".env"
if env.exists():
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

from app import application  # noqa: E402

if __name__ == "__main__":
    # Локальний запуск для перевірки: TRACKER_DEV=1 uv run python wsgi.py
    from werkzeug.serving import run_simple

    run_simple("127.0.0.1", 5050, application)
