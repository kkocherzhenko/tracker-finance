# Trajet UI polish brief (from finance-app design research)

Goal: make the existing mobile report, "+ Готівка" form, limits and login screens feel like a polished banking app (monobank, Revolut, Monzo, YNAB, Copilot Money patterns). **Presentation only.**

## Hard rules
- Follow CLAUDE.md. Touch only: `CSS` and the `block_*` / `render()` HTML in `report.py`, page HTML/CSS in `app.py`, `static/` (no new icons/manifest changes). Do **not** touch `load()`, saved queries, `import.py`, `cashbook.py`, `*.beancount`, `rules*.csv`, `limits.csv` format, routes, form field names (`amount`, `description`, `account`, `date`, shared toggle), CSRF, login logic, `visible()`.
- No new dependencies, no external fonts/images/CDNs. Icons = inline SVG (24px, stroke 1.8, `currentColor`), like the existing tab bar.
- Colors: only the existing CSS variables in `report.CSS` (Trajet palette from `palette-prompt-en.md`: `--bg --surface --border --text --text-muted --accent --accent-strong --on-accent --positive --negative --warning --cat1..8`). No new hues; tints via `color-mix()` of existing tokens. Do not add a dark theme (feature #3 is separate).
- Keep all strings asserted in `test_privacy.py` (e.g. `"з 250 зл"`, `"бачить лише"`, names in header).
- Respect `prefers-reduced-motion: reduce` (disable all animations below).
- Done = `uv run python check.py` silent + control figures unchanged, `uv run python -m unittest test_privacy` green, `uv run python report.py` regenerates `report.html`, screenshots at 390px of Витрати / Відкладено / Фіксовані / Ліміти / Готівка / Вхід look right. Update `PROGRESS.md`, commit in Ukrainian. Work in small commits, one item per commit.

## Changes (priority order)

### 1. Money typography (Revolut, Wise)
- Global `.num { font-variant-numeric: tabular-nums; }` on every amount.
- Hero amounts: currency suffix smaller and muted: `8 982 <span class="cur">зл</span>` with `.cur { font-size:.5em; font-weight:500; color:var(--text-muted); margin-left:.15em }`. Do it in one helper (e.g. `zl_html()`), leave `zl()` plain-text output unchanged (tests and titles use it).

### 2. Hero + month-over-month delta chip (Revolut analytics, Copilot)
- Under the "Куди йдуть гроші" hero, show a pill comparing with the previous month for the same view, computed from existing `d["categories"][prev_key, view]` sums (render-time arithmetic only): `▲ 12% до серпня` (more spent = `--negative` tint) / `▼ 8% до серпня` (`--positive` tint). Hide for the first month and when the current month is partial (`month_caption` contains "неповний"); for partial months show nothing rather than a misleading compare.

### 3. Category ring + icon list (monobank statistics)
- Above the existing bar list add an SVG donut (160px, stroke 18, 2px gaps between segments, `--cat1..8` in the same order as the rows, >8 → same colors at 60% opacity as now). Center: total + "витрачено". No library; compute arcs in Python.
- Each category row gets a 36px round icon chip: background `color-mix(in srgb, var(--catN) 18%, var(--surface))`, icon stroke `var(--text)`. Map display name (`category_name()`) → inline SVG: Продукти=basket, Житло=house, Доставка їжі=scooter/bag, Кафе=cup, Транспорт=bus, Спорт=dumbbell, Підписки=repeat, Мобільний оператор=phone, Інтернет=wifi, Електрика=bolt, Покупки=shopping bag, Краса і побут=sparkle, Розваги=ticket, Інше=dots, Без категорії=question. Unknown → first letter. Show `% of total` under the name in `--text-muted` small.
- Row tap target ≥ 48px.

### 4. Limits as a budget tracker (YNAB, Revolut budgets, Monzo targets)
- Keep the 3 states (fine/near/over at 80%/100%), add a text chip per row: `В нормі` / `Близько` / `Перевищено` (not color-only).
- Add a "today" pace marker for the current partial month only: a 2px `--text` tick on the track at `last_day / days_in_month`. Thresholds stay as they are.
- Under each bar: `Лишилось 320 зл · ≈ 21 зл/день` (limit − spent; per-day = remaining / days left in month, only for the partial month; when over: existing `перевищено на X зл`).
- Bar height 10px, track `--border`, radius 5px; bar grows from 0 on load (`transform:scaleX`, 400ms ease-out).
- Empty state: icon (gauge) + "Лімітів ще немає" + primary button "Задати ліміт" → existing settings URL.

### 5. Alert banner → chips (monobank/Revolut notifications)
- Replace the wall-of-text `.alert` with a title line "Увага, ліміти" + horizontally scrollable chips (`overflow-x:auto`, no wrap), one per hot limit: `Продукти · Марко  +400 зл` (over: `--negative` tint) or `Доставка їжі · Марко  98%` (near: `--warning` tint). Tapping the banner switches the bottom tab to Ліміти (reuse existing JS `s='limits'; show()`). Max 1 line tall + title.

### 6. Savings rate ring (monobank «Банка» fill metaphor)
- Replace plain hero on "Скільки відкладено" with a 140px progress ring: arc = savings rate (clamped 0–100%), stroke `--accent`, track `--border`, center `31%` big + "відкладено". Negative rate → ring in `--negative`, center shows the negative %. Keep the existing sentence below and the existing "no income yet" state.

### 7. "+ Готівка" form like a payment screen (Revolut/monobank transfer)
- Amount first: large centered input (font 2.75rem, weight 600, `inputmode="decimal"`, no border, `зл` suffix muted), autofocus kept.
- Category: replace the visible `<select>` with a 3-column grid of radio chips (icon + name) **using the same `name="account"` and same values**; keep it a native radio group (keyboard + screen reader OK). Server validation unchanged.
- Date: chips "Сьогодні" / "Вчора" / "Інша дата" that set the existing `<input type=date name=date>` (shown only for "Інша дата"); keep min/max.
- Shared/private stays a segmented control (style like `#people`).
- Sticky bottom primary button "Зберегти" full width above safe area. On success, existing flash toast + `navigator.vibrate?.(10)`.

### 8. Motion (subtle, Copilot/monobank 2.0)
- Section switch: panel fade+translateY(6px) 180ms. Bars/rings grow on first show of a panel. Buttons keep `scale(.98)` on press. Nothing longer than 400ms. All off under reduced motion.

### 9. Empty & partial states (Monzo/YNAB tone)
- Every empty card: 40px line icon in `--accent`, one plain sentence, and an action if one exists. Partial month caption stays a warning pill; add a small "дані до 15 жовтня" hint near the hero instead of only in caption.

### 10. Login (Wise clarity)
- Center card, Trajet mark from `static/icon-192.png` (already exists) at 64px above "Наші фінанси", subtle `--bg` → `color-mix(--accent 15%, --bg)` vertical gradient background, inputs 52px high, radius 16px, focus ring `2px solid var(--accent)`, error text with icon in `--negative`.

## Out of scope (ask first)
Daily cumulative "pace" line chart (needs a new per-day query), dark theme, custom fonts, merchant logos, any data/settlement logic.
