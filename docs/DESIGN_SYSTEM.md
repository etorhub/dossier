# Design System

Styling conventions for the Dossier user-facing web app. Styles live in [`app/static/dossier.css`](../app/static/dossier.css), linked from [`templates/base.html`](../templates/base.html).

The ops dashboard (`ops/templates/ops/`) uses Bootstrap 5 separately and is out of scope here.

---

## Principles

1. **No build step** — plain CSS served as a static file; no Tailwind, PostCSS, or npm.
2. **HTMX-only interactivity** — no JS frameworks; the only inline script in `base.html` is Web Speech API (TTS) and service worker registration.
3. **Accessibility-first** — large touch targets, high-contrast mode, semantic HTML, reduced-motion support. See [`.cursor/rules/accessibility.mdc`](../.cursor/rules/accessibility.mdc).

---

## Design tokens

All colors and sizing use CSS custom properties on `:root`, overridden by `prefers-color-scheme`, `body.light`, `body.dark`, and `body.high-contrast` (high-contrast always wins — do not reorder those rules).

### Backgrounds and surfaces

| Token | Purpose |
| --- | --- |
| `--bg` | Page background |
| `--surface` | Subtle panels (stat tiles, chips) |
| `--surface-2` | Progress bar track, secondary surfaces |

### Text

| Token | Purpose |
| --- | --- |
| `--fg` | Primary text |
| `--fg-muted` | Labels, secondary copy |
| `--fg-faint` | Meta text, inactive nav |
| `--muted` | Legacy alias for `--fg-muted` |

### Accent and semantic

| Token | Purpose |
| --- | --- |
| `--accent`, `--accent-hover`, `--accent-bg`, `--accent-text` | Links, primary buttons, focus rings |
| `--error` | Error messages (`.flash-error`) |
| `--success` | Read badges, success states |
| `--border`, `--border-strong` | Dividers, input borders |

### Typography

| Token | Purpose |
| --- | --- |
| `--font-ui` | System UI stack (nav, forms, meta) |
| `--font-reading` | Lora serif (article body, headlines) |
| `--text-base` | Body size (`1.125rem` / 18px) |
| `--text-sm` | Secondary UI copy |
| `--text-ui` | Button and compact UI text |

### Layout and touch

| Token | Purpose |
| --- | --- |
| `--touch-min` | Minimum interactive target (`48px`) |
| `--radius`, `--radius-sm`, `--radius-lg`, `--radius-full` | Border radii |
| `--shadow-sm`, `--shadow`, `--shadow-lg` | Elevation |

### Gamification

| Token | Purpose |
| --- | --- |
| `--streak-flame` | Streak counter accent |
| `--progress-from`, `--progress-to` | Session progress bar gradient |
| `--celebrate-from`, `--celebrate-to` | Completion screen gradient |

---

## Components

### Buttons

| Class | Use when |
| --- | --- |
| `.btn` | Default secondary action |
| `.btn-primary` | Primary form submit, main CTA |
| `.btn-ghost` | Tertiary / navigation actions with accent text |
| `.btn-link` | Inline text-style action (e.g. “Read full story”) |
| `.btn-next` | Session “next article” CTA (gradient) |
| `.btn-sm` | Compact ghost button (e.g. “View original”) |

Global `button`, `input[type="submit"]`, and `.btn` inherit `--touch-min` sizing.

### Cards and layout

| Class | Purpose |
| --- | --- |
| `.article-card` | Feed / review story row |
| `.article-card--expanded` | Inline expanded article |
| `.auth-card` | Centered login/register/error forms |
| `.auth-card--centered` | Centered content inside auth card (500 page) |
| `.session-wrap` | Guided reading session container |
| `.completion` | Digest completion celebration |
| `.stat-tile` | Stats page metric block |

### Forms

| Class | Purpose |
| --- | --- |
| `.form-group` | Label + input group |
| `.form-group--actions` | Standalone submit row (setup/settings) |
| `.form-actions` | Stacked full-width actions (auth forms) |
| `.form-actions--row` | Horizontal button row |
| `.flash-success`, `.flash-error` | Inline status messages |

### Session and feed

| Class | Purpose |
| --- | --- |
| `.session-message` | Empty / loading states |
| `.session-message-sub` | Secondary hint under loading message |
| `.progress-bar`, `.progress-fill` | Progress indicator (width set inline) |
| `.read-badge` | “Read” marker in review |

---

## Utilities

| Class | Purpose |
| --- | --- |
| `.text-center` | Center text |
| `.text-muted` | Muted paragraph (UI font, `--fg-muted`) |
| `.text-subtle` | Smaller secondary hint |
| `.inline-form` | Inline form (e.g. logout in nav) |
| `.alert`, `.alert-info` | Bordered alert banner |
| `.btn-row` | Horizontal button group with gap |
| `.article-title-link` | Card title link (inherits color, no underline) |

Prefer utilities over new inline `style=` attributes.

---

## Jinja macros

Shared patterns in [`templates/macros/ui.html`](../templates/macros/ui.html):

```jinja
{% from 'macros/ui.html' import alert_box, form_submit %}

{{ form_submit(_('Save')) }}
{{ form_submit(_('Log in'), 'form-actions') }}

{% call alert_box(_('Title')) %}
  <p>Body copy</p>
{% endcall %}
```

---

## Rules for contributors

1. **No hardcoded hex colors in templates** — use tokens or existing component classes.
2. **No new inline `style=`** except dynamic values (e.g. progress bar `width: N%`).
3. **Extend tokens before adding one-off colors** — add to all theme blocks (light, dark, high-contrast).
4. **New UI strings** — wrap in `_()` / `gettext()` and run the i18n workflow.
5. **Do not add JavaScript files** — HTMX attributes only (TTS exception in `base.html`).

---

## Theming

User profile drives body classes set in `base.html`:

- `high-contrast` — black/white, all semantic colors flatten to high contrast
- `dark` / `light` — manual override of system preference
- (none) — follows `prefers-color-scheme`

Test visual changes in all three modes before shipping.
