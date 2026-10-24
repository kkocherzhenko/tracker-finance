Update the tracker's color palette to match the new Trajet logo (an ice mountain: blues, white, dark navy). Change colors only: do not touch UI text (the interface is in Ukrainian), layout, logic or data.

1. Find every place where colors are defined: the report CSS (report.html and templates), the login page, any Fava customization, and chart colors in JS/Python. Consolidate them into CSS variables in one place (`:root`) and use those variables everywhere instead of literal values.

2. Light theme (default):
   --bg: #E9EFF3         page background (ice)
   --surface: #FFFFFF    cards, tables, forms
   --border: #D0DCED     borders, dividers, input backgrounds
   --text: #1E3550       body text, headings (dark navy)
   --text-muted: #53677D captions, secondary text
   --accent: #739BBF     main chart series, icons, active tabs, progress bars (glacier blue; too light for text)
   --accent-strong: #2B4C70  links, buttons, hover, highlighted amounts
   --on-accent: #FFFFFF  text on buttons

3. Dark theme (if the project already has a dark theme or uses prefers-color-scheme, recolor it with these values; if not, do not add one):
   --bg: #0F1B29  --surface: #16273A  --border: #2A4260
   --text: #E9EFF3  --text-muted: #9DB3CB
   --accent: #9DBBD8  --accent-strong: #C9D8EA  --on-accent: #0F1B29

4. Semantic colors (income/expense, limits, errors), muted to fit the palette:
   --positive: #2F7A59   --negative: #C2534B   --warning: #946A1E
   Dark theme: --positive: #5DB38D  --negative: #E07A72  --warning: #E0B860

5. Chart category colors, in this order:
   #1E3550, #739BBF, #A9C1DA, #4A6F94, #D0DCED, #2B4C70, #8FB0CF, #53677D
   If there are more than eight categories, reuse these colors with hatching or 60% opacity instead of adding new hues. Adjacent segments must never share a color.

6. Check contrast: body text against its background must be at least 4.5:1 (WCAG AA) in both themes. If any pair fails, darken or lighten that color within the same blue range and tell me what you changed.

7. If there is a favicon or PWA icons, leave them alone: I will add the logo separately.

8. When done, run the project, open the report and the login page, and confirm everything is recolored and nothing broke (bean-check stays silent, Olya's and Marko's control figures are unchanged). Give me a short list of the files you changed.
