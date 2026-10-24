# Наші фінанси: трекер Олі й Марка

Спільний фінансовий трекер на Beancount 3. Імпортує дві банківські виписки (Олі й Марка), звіряє їх з банком через `bean-check` і показує щомісячний звіт: витрати за категоріями, норму заощаджень, фіксовані й змінні витрати. Марко відкриває його з телефону за паролем і додає готівкові витрати; сторінку можна встановити на головний екран (PWA).

Усі дані в репозиторії вигадані: це навчальне завдання (WIT 5.0).

## Перевірка однією командою

Потрібен [uv](https://docs.astral.sh/uv/getting-started/installation/).

```sh
uv run python check.py
```

Команда перезбирає `transactions.beancount` з обох виписок, запускає `bean-check main.beancount` і друкує контрольні цифри. Очікуваний результат:

```
2. bean-check main.beancount
   без повідомлень

3. Змінні витрати (без #fixed), PLN
   хто    місяць            є  має бути
   Оля    серпень     2195.21   2195.21  OK
   Оля    вересень    2582.42   2582.42  OK
   Марко  серпень     1855.57   1855.57  OK
   Марко  вересень    2432.83   2432.83  OK

Усе збігається.
```

Змінні витрати = усі витрати без тегу `#fixed`. Фіксовані в Олі: оренда, ZTM, Netflix, Spotify, Claude.ai, Play. У Марка: Orange (інтернет і телефон), PGE, Zdrofit, YouTube Premium.

## Що де лежить

| Файл | Що робить |
|---|---|
| `data/statement.csv`, `data/marko-statement.csv` | Виписки Олі й Марка (вигадані), 1 серпня — 15 жовтня 2026 |
| `rules.csv`, `rules-marko.csv` | Правила категорій для кожного банку |
| `import.py` | Читає обидва формати CSV, пише `transactions.beancount` з перевіркою залишку банку |
| `main.beancount` | Рахунки по людях (`Expenses:Марко:Продукти`), збережені запити, `include` |
| `cash.beancount` | Готівка, додана з телефону. Створюється автоматично, у git не потрапляє |
| `check.py` | Команда перевірки вище |
| `report.py` | Звіт; `uv run python report.py` пише статичний `report.html` |
| `app.py`, `cashbook.py`, `wsgi.py` | Веб-застосунок: вхід, звіт, форма готівки, Fava на `/fava/` |
| `make_env.py` | Створює `.env` з секретним ключем і хешами паролів |
| `static/` | Маніфест, іконки, service worker для встановлення на телефон |

## Запуск на своєму комп'ютері

```sh
uv run python make_env.py            # логін і пароль, пише .env
TRACKER_DEV=1 uv run python wsgi.py
```

Відкрити http://127.0.0.1:5050. `TRACKER_DEV=1` дозволяє http без HTTPS, тільки для локальної перевірки. Fava окремо, як на воркшопі: `uv run fava -p 5050 main.beancount`.

## Публікація на PythonAnywhere (безкоштовно)

1. Зареєструвати безкоштовний акаунт Beginner на [pythonanywhere.com](https://www.pythonanywhere.com/). Адреса буде `https://ЛОГІН.pythonanywhere.com`.
2. **Consoles → Bash**, виконати по черзі:
   ```sh
   git clone https://github.com/kkocherzhenko/tracker-finance.git
   cd tracker-finance
   mkvirtualenv --python=python3.12 tracker
   pip install -r requirements.txt
   python import.py
   python make_env.py
   ```
   `make_env.py` питає логіни й паролі (наприклад, `marko` і окремий тестовий для перевіряючих) і пише `.env` з хешами. Відкритих паролів ніде не лишається.
3. **Web → Add a new web app → Manual configuration → Python 3.12.**
4. На сторінці застосунку:
   - **Virtualenv:** `/home/ЛОГІН/.virtualenvs/tracker`
   - **Source code:** `/home/ЛОГІН/tracker-finance`
   - **WSGI configuration file:** відкрити й замінити весь вміст на
     ```python
     import sys
     sys.path.insert(0, "/home/ЛОГІН/tracker-finance")
     from wsgi import application
     ```
   - **Security → Force HTTPS:** увімкнути.
5. Натиснути **Reload**. Відкрити `https://ЛОГІН.pythonanywhere.com` на телефоні, увійти, у меню браузера вибрати «На екран Додому» (iPhone) або «Встановити застосунок» (Android).
6. Безкоштовний застосунок треба продовжувати раз на місяць кнопкою **Run until 1 month from today** на вкладці Web.

Оновити код на сервері: `cd ~/tracker-finance && git pull && python import.py`, потім **Reload**. Записи готівки в `cash.beancount` при цьому не зачіпаються.

## Безпека

- **Без входу немає даних.** Кожна сторінка, крім входу, маніфесту й іконок, перенаправляє на `/login`; Fava на `/fava/` закрита тим самим входом. Service worker не кешує сторінок з даними.
- **Секрети лише в змінних середовища.** `SECRET_KEY` і `TRACKER_USERS` (логін і хеш пароля scrypt) читаються з середовища; на сервері їх задає файл `.env`, який створює `make_env.py` і який не потрапляє в git.
- **Лише HTTPS.** PythonAnywhere видає сертифікат для `*.pythonanywhere.com`; Force HTTPS на сервері плюс перенаправлення http→https і заголовок HSTS у самому застосунку. Cookie сесії `Secure`, `HttpOnly`, `SameSite=Lax`, форми із CSRF-токеном.
- **Лише вигадані дані** в репозиторії й на сервері.
- **Додатково: обмеження спроб входу** (5 невдалих спроб з однієї адреси → пауза 5 хвилин). Навіть для двох людей адреса `*.pythonanywhere.com` публічна, і боти перебирають паролі на всьому, що знаходять; це кілька рядків коду і нуль зусиль для Олі й Марка. 2FA і шифрування полів не додавали: для двох людей із вигаданими даними це ускладнення без користі.

## Що спрощено

- Один спільний вхід для обох: кожен бачить усі витрати (функція 12 «особисті дані» з частини 1 — наступна версія).
- Готівку записуємо як витрату з рахунку `Assets:<людина>:Готівка` без звірки залишку готівки.
- Хто кому винен за оренду й продукти (функція 9) не рахуємо.
- Безкоштовний тариф PythonAnywhere: одне веб-застосування, обмежений процесор, продовження раз на місяць; перше відкриття може бути повільним.
