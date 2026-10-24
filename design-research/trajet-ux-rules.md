# Trajet UX rules: clear for non-technical users (paste into Claude Code)

Apply these rules to the tracker repo `kkocherzhenko/tracker-finance`. Goal: Marko (not technical) can open, read and add cash on his phone with zero help. This file complements `design-research/trajet-ui-brief.md` (visual polish items 1–10); do not redo those, but where both apply these rules win on usability/accessibility. Colors come only from the palette in `logo/palette-prompt-en.md` (CSS variables in `report.CSS`).

## 0. Hard limits (read first)
- Presentation only: CSS, HTML in `block_*`/`render()` of `report.py`, page HTML/CSS in `app.py`, `static/`. Small inline JS for UI behaviour is OK.
- Never touch: `load()`, saved queries, `import.py`, `cashbook.py`, `*.beancount`, `rules*.csv`, `limits.csv` format, `check.py`, routes, form field names (`amount`, `description`, `account`, `date`, shared toggle), CSRF, login logic, `visible()`, server-side validation.
- `uv run python check.py` must stay silent with control figures unchanged (Olia Aug 2195.21 / Sep 2582.42, Marko Aug 1855.57 / Sep 2432.83). bean-check output unchanged.
- Keep every string asserted in `test_privacy.py` (e.g. `"з 250 зл"`, `"бачить лише"`, names in header). Keep `zl()` plain-text output unchanged; format for display in an HTML helper.
- No new dependencies, fonts, CDNs, trackers or analytics. Inline SVG icons only.
- If a rule conflicts with a hard limit, skip the rule and list it in the final report.
- Small commits, one rule group per commit, messages in Ukrainian. Update `PROGRESS.md`.

## 1. Navigation
- Max 5 bottom tabs (Material: 3–5), each icon + visible Ukrainian text label (never icon-only). Active tab: `--accent-strong` text + indicator, not color alone.
- Tab bar fixed at bottom, solid `--surface` background (no translucency/blur), `padding-bottom: env(safe-area-inset-bottom)`.
- Same order and position of tabs on every screen; controls never appear/disappear or move by context.
- Report header order is fixed: view switch `Разом / Оля / Марко`, then month picker, then content. Both visible without scrolling at 390×844.
- View switch = segmented control, `role="radiogroup"` (or buttons with `aria-pressed`), selected segment filled `--accent-strong` + `--on-accent` text.
- Month picker: `‹` prev / month name / `›` next, each ≥ 44×44 px; disable `›` on the latest month and `‹` on the first (visibly + `aria-disabled`). Label as `Вересень 2026`, not `2026-09`.
- Selected view and month survive reload and tab switch (URL params or `localStorage` wrapped in try/catch).
- Primary action `+ Готівка` reachable in 1 tap from every report screen (tab or FAB in thumb zone, bottom 1/3 of screen).
- Every non-home screen has a visible back/close control with a text label (`Назад`, `Скасувати`).
- No hidden gestures as the only way to do something (no swipe-only, long-press-only, drag-only; WCAG 2.5.7).

## 2. Forms (`+ Готівка`, login, limits)
- Add cash in ≤ 3 taps after the form opens for the common case: type amount → tap category → `Зберегти`. Date defaults to today, shared/private defaults to the last used value.
- Fields order: Сума → Категорія → Опис (optional) → Дата → Спільна/Особиста. Only one column.
- Every field has a visible label above it. Placeholder is never the label. Mark optional fields `(необовʼязково)`; do not mark required ones with `*` only.
- Amount: `inputmode="decimal"`, `autocomplete="off"`, accept both `,` and `.` as decimal separator and spaces in input (normalize client-side before submit; server value format unchanged). Font ≥ 1.75rem, `зл` suffix visible.
- Description: `autocapitalize="sentences"`, `enterkeyhint="done"`, max length shown only when near it.
- Login: `autocomplete="username"` / `autocomplete="current-password"`, password show/hide toggle (button ≥ 44 px, `aria-label="Показати пароль"`), paste allowed, no CAPTCHA or puzzles (WCAG 3.3.8). `enterkeyhint="go"`.
- Limits form: `inputmode="numeric"`, show current spend next to each limit input.
- Inputs ≥ 48 px high, font-size ≥ 16 px (prevents iOS zoom), border with ≥ 3:1 contrast to background (use `--text-muted`, not `--border`).
- Primary button full width, ≥ 48 px high, label is a verb: `Зберегти`, `Увійти`, `Зберегти ліміт`. Never `OK`/`Submit`.
- Disable the submit button only while submitting (show `Зберігаю…`), prevent double submit; never disable it to signal invalid input.
- On server error, keep everything the user typed (re-render values).
- Never ask to re-enter data the app already has (WCAG 3.3.7).

## 3. Feedback, errors, empty and loading states
- After saving cash: toast `Додано 45,00 зл · Продукти` (amount + category, specific), visible ≥ 4 s, `role="status"`, plus the new item visible in the report on next view. `navigator.vibrate?.(10)` optional.
- Toast/alert never covers the tab bar or focused field (WCAG 2.4.11).
- Validate on blur or submit, never while the user is still typing the first value.
- Error text: right under the field, icon + text in `--negative` on `--surface`, field border `--negative`, `aria-invalid="true"`, `aria-describedby` → error id. Focus the first invalid field on submit.
- Error message = what is wrong + how to fix, plain Ukrainian, no codes, no blame. Examples in §4.
- Server/network failure: full sentence + retry button. Never show a stack trace, HTTP code or English text.
- Loading over 300 ms: skeleton or `Завантаження…` text; never show an empty state while loading.
- Every empty state = line icon (40 px, `--accent`) + one sentence why it is empty + action button if one exists. Never a blank card or `0` without context.
- Partial month (data till 15 Oct): show `Дані до 15 жовтня` near the hero amount, not only in a caption.
- Destructive/irreversible action (if any exists): confirmation with the object named (`Видалити ліміт «Продукти»?`) and buttons `Видалити` / `Скасувати`; prefer undo toast where possible.

## 4. Microcopy (Ukrainian UI)
- Plain everyday words. Banned in UI: `транзакція`, `акаунт/рахунок` (as Beancount account), `ledger`, `query`, `posting`, `bean-check`, `Expenses:…`, English words, category paths. Use `витрата`, `категорія`, `спільна`, `особиста`.
- Address the user as `ви` consistently, or neutral imperative; pick one and use it everywhere.
- Sentence case for buttons and headings. No ALL CAPS, no exclamation marks except success toasts.
- Numbers in text are formatted (see §6). Months as words.
- One term per concept across all screens (e.g. always `Разом`, never mixing `Разом`/`Спільне`/`Усі` for the same view).
- Error templates:
  - empty amount: `Введіть суму, наприклад 25,50`
  - bad amount: `Сума має бути числом більше 0`
  - no category: `Оберіть категорію`
  - future date: `Дата не може бути в майбутньому`
  - wrong login: `Неправильне імʼя або пароль. Спробуйте ще раз.`
  - network: `Немає звʼязку. Перевірте інтернет і спробуйте ще раз.` + `Спробувати ще`
- Empty templates: no expenses `У цьому місяці ще немає витрат` + `+ Готівка`; no limits `Лімітів ще немає` + `Задати ліміт`.
- Privacy hint, short and calm, where private data is hidden: keep existing `бачить лише …` wording.
- Max ~12 words per helper line; no paragraphs on mobile.

## 5. Accessibility, contrast, touch
- Touch targets: every interactive element ≥ 44×44 CSS px (Apple HIG); primary buttons, tabs, category chips, month arrows ≥ 48 px (Material). Gap ≥ 8 px between adjacent targets. Expand hit area with padding, not by shrinking spacing.
- Text contrast ≥ 4.5:1, large text (≥ 24 px or ≥ 18.66 px bold) ≥ 3:1; UI components and meaningful graphics (input borders, focus ring, bar fills, chart segments carrying meaning) ≥ 3:1 (WCAG 1.4.3, 1.4.11).
- Measured palette facts (light theme), obey them:
  - `--text` 12.5:1, `--text-muted` 5.8:1 on `--surface`, 5.0:1 on `--bg`: OK for text.
  - `--accent` #739BBF = 2.9:1 on white: never for text, focus rings or the only cue of meaning. Decorative fills only; use `--accent-strong` (8.9:1) for focus rings, links, selected states.
  - `--negative` 4.5:1 / `--positive` 5.2:1 / `--warning` 4.8:1 on `--surface` only. On `--bg` or tinted chips they fall below 4.5:1: there use `--text` for the label and the semantic color for an icon/border, or darken the tint until ≥ 4.5:1.
  - `--border` 1.4:1: dividers only, never the only boundary of an input or button.
- Never color alone: limit states have text chips (`В нормі` / `Близько` / `Перевищено`), deltas have `▲/▼` + sign, chart segments have labels/legend rows with amounts.
- Visible focus for keyboard: `:focus-visible { outline: 2px solid var(--accent-strong); outline-offset: 2px }`. Never `outline: none` without replacement.
- Semantic HTML: real `<button>`, `<a>`, `<label for>`, `<fieldset><legend>` for radio groups, one `<h1>` per screen, landmarks `<header> <main> <nav>`.
- Icon-only controls get `aria-label` in Ukrainian. Decorative SVG `aria-hidden="true"`.
- Charts/rings: text alternative (`aria-label` with the key numbers) and the same numbers visible in the list.
- Page `lang="uk"`. Base font 16 px, line-height ≥ 1.4; layout works at 200 % text zoom and at 320 px width without horizontal scroll.
- No translucent/blurred overlays over content; text never on images.
- `prefers-reduced-motion: reduce` disables all transitions/animations. No animation > 400 ms, no looping animation.
- `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`; never `user-scalable=no` or `maximum-scale=1`.

## 6. Numbers, currency, dates (PLN, uk-UA)
- Display format = `Intl.NumberFormat('uk-UA')` style: thousands separator non-breaking space (U+00A0), decimal comma: `1 234,50 зл`. Currency label `зл` after the number, separated by U+00A0 (never wrap between number and `зл`).
- Show 2 decimals for single expenses and form confirmations; whole numbers allowed for big totals and hero amounts, but be consistent within a screen. Never show floats like `2195.2100000001`.
- Negative values: real minus `−` (U+2212) or explicit wording (`перевищено на 400 зл`), never `--` or parentheses.
- Percentages: `31 %` (uk spacing with U+00A0) or `31%`; pick one and use everywhere; round to whole numbers in UI.
- All amounts: `font-variant-numeric: tabular-nums`; right-align amounts in lists.
- Dates: `15 жовтня`, `15 жовтня 2026` when year differs from current; months in nominative for headers (`Вересень 2026`), genitive inside dates (`15 вересня`). Relative `Сьогодні`/`Вчора` for the last two days. Never ISO dates in UI.
- Formatting is render-only. Do not change values stored, parsed, compared or printed by `check.py`/tests.

## 7. Performance (free hosting, phone on mobile data)
- Report HTML + CSS + JS for one screen ≤ 150 KB gzipped excluding icons; no web fonts; SVG inline, no images except the PWA icon.
- Target on a mid phone (Lighthouse mobile, simulated 4G): LCP ≤ 2.5 s after the server is awake, INP ≤ 200 ms, CLS ≤ 0.1.
- Reserve space for charts and toasts (fixed sizes) so nothing jumps.
- Tab/view/month switch with already loaded data must respond < 100 ms (no full reload if the data is already on the page).
- Cold start of free hosting can take up to a minute: login page shows `Сервер прокидається, це може тривати до хвилини…` after 3 s of waiting instead of a blank screen (only if achievable without touching routes; otherwise list it as skipped).
- JS failures must not hide data: the report stays readable with JS disabled.

## 8. Privacy-friendly UX for two users
- Always show who is logged in (`Оля` / `Марко`) in the header and a `Вийти` control ≤ 2 taps away.
- Make the current scope obvious: the active view `Разом / Оля / Марко` and a one-line hint of what is included (e.g. `Спільні витрати і ваші особисті`). Keep existing `бачить лише` text.
- Private expenses of the other person never appear in UI, totals, chart tooltips, `aria-label`s, `title` attributes or HTML comments (visibility logic stays server-side in `visible()`; do not change it, just never re-expose data in new markup).
- `+ Готівка` shared/private toggle: labels `Спільна (бачать обоє)` / `Особиста (бачите лише ви)`; default = last choice; current choice repeated in the success toast.
- No amounts in `<title>`, push/toast text that persists, or URLs.
- Session expiry: redirect to login with `Сесія завершилась, увійдіть ще раз`, keep the form draft if possible client-side.
- Login page shows no data and no names other than the app name.

## 9. Self-audit (run at the end, report pass/fail per line)
1. `uv run python check.py` silent, control figures exactly as in §0. `uv run python -m unittest test_privacy` green. `uv run python report.py` regenerates `report.html`.
2. `git diff --stat` touches only allowed files from §0. No changes in `check.py`, importers, ledgers, CSV, routes, field names.
3. Playwright (preinstalled) at 390×844 and 320×640: screenshots of Вхід, Витрати (Разом/Оля/Марко), month switch, Ліміти, Готівка (empty, error, success). No horizontal scroll (`document.documentElement.scrollWidth <= innerWidth`).
4. Script: every `a, button, input, select, [role=button], label` for radio chips has bounding box ≥ 44×44 (primary ≥ 48 high). List violators.
5. Contrast script over computed styles: all visible text ≥ 4.5:1 (≥ 3:1 large), input borders and focus ring ≥ 3:1. List violators.
6. Grep rendered HTML for banned words (§4) and for ISO dates `\d{4}-\d{2}-\d{2}` and raw decimals `\d\.\d{2} зл` in visible text; must be none.
7. Add 1 зл test cash as Marko in ≤ 3 taps after opening the form; toast names amount + category; it appears after reload. Then remove the test entry the same way the project normally does (do not hand-edit ledgers if that is not the normal path; ask).
8. Keyboard only: Tab through login and cash form, focus always visible and never hidden by the tab bar/toast.
9. `prefers-reduced-motion: reduce` emulated: no transitions.
10. Log in as Olia, then Marko: no other person's private expense visible anywhere (including `aria-label`/`title`).
11. Lighthouse mobile (if available) for the report: Accessibility ≥ 95, LCP/INP/CLS as in §7.
12. Final message: list of changed files, rules applied, rules skipped and why.

## Sources
NN/g heuristics https://www.nngroup.com/articles/ten-usability-heuristics/ · touch targets https://www.nngroup.com/articles/touch-target-size/ · error messages https://www.nngroup.com/articles/error-message-guidelines/ · empty states https://www.nngroup.com/articles/empty-state-interface-design/ · mobile input https://www.nngroup.com/articles/mobile-input-checklist/ · placeholders https://www.nngroup.com/articles/form-design-placeholders/ · Liquid Glass (2025) https://www.nngroup.com/articles/liquid-glass/ · WCAG 2.2 https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/ · Apple HIG https://developer.apple.com/design/human-interface-guidelines/buttons · Material 3 https://m3.material.io/foundations/designing/structure · Android touch target https://support.google.com/accessibility/android/answer/7101858 · Intl.NumberFormat https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/NumberFormat/NumberFormat · Core Web Vitals https://web.dev/articles/vitals · INP https://web.dev/articles/inp · fintech trust https://www.mindtheproduct.com/ux-that-builds-trust-what-top-fintechs-get-right/ · GOV.UK errors https://design-system.service.gov.uk/components/error-message
