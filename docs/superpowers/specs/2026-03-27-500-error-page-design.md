# 500 Error Page Design

**Date:** 2026-03-27
**Scope:** Full-page 500 server error — visual error state with retry mechanism
**Approach:** Option B — `templates/500.html` extends `base.html`

---

## Problem

When a Flask route or service throws an unhandled exception, Flask returns a plain, unstyled error page. Users have no feedback, no way to retry, and no way to navigate back to the feed.

## Solution

Register a `@app.errorhandler(500)` in `create_app()` that renders a styled `templates/500.html` template. The page uses the existing design system (CSS variables, button classes, layout) and presents two recovery actions: reload the page, or go back to the feed.

---

## Visual Layout

A centered card inside the standard `<main>` block of `base.html`:

1. **Icon** — large SVG circle with `×` inside, stroked in `--fg-muted`. No color fill, no animation.
2. **Heading** — `_('Something went wrong')` using the `h1` style.
3. **Body copy** — `_('An unexpected error occurred. You can try again or go back to the feed.')` in `--fg-muted` at `0.9rem`.
4. **Actions row** — two controls, side by side on desktop, stacked on mobile:
   - `.btn-primary` button with `onclick="window.location.reload()"` — labelled `_('Try again')`
   - `.btn-ghost` anchor to `url_for('reader.index')` — labelled `_('Go to feed')`
5. No error code, no stack trace, nothing technical surfaced to the user.

The card reuses the `.auth-card` dimensions and `--radius-lg` to stay consistent with the existing auth pages.

---

## Backend

- One `@app.errorhandler(500)` registered in `create_app()` in `app/__init__.py`.
- Returns `render_template("500.html"), 500`.
- If `HX-Request` header is present (HTMX partial), returns an empty 500 response — avoids injecting a full HTML page into a partial swap target. HTMX partial error handling is out of scope for this spec.

---

## i18n

All user-facing strings use `_()`. After adding strings, run:

```
pybabel extract && pybabel update && pybabel compile
```

Strings to translate:
- `Something went wrong`
- `An unexpected error occurred. You can try again or go back to the feed.`
- `Try again`
- `Go to feed`

---

## Files Changed

| File | Change |
|------|--------|
| `app/__init__.py` | Add `@app.errorhandler(500)` inside `create_app()` |
| `templates/500.html` | New template extending `base.html` |

No new blueprints, no new routes, no new CSS files.

---

## Out of Scope

- HTMX partial 500 handling (inline error banners in swap targets)
- 404 or other error codes
- Stack trace display for operators (ops dashboard handles that separately)
