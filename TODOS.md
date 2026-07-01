# TODOS

Design debt and deferred implementation items. Each item includes context so it can be picked up in a future session.

---

## Design Debt

### [A11Y] Fix .feed-count contrast ratio

**What:** Update `.feed-count` in `base.html` to use `--fg-muted` (`#6b7280`) instead of `--fg-faint` (`#9ca3af`).

**Why:** `--fg-faint` on `--bg` = 2.9:1 contrast ratio. WCAG AA requires 4.5:1 for small text (< 18pt). The article count is rendered at `0.75rem` (12px) — fails the requirement.

**Pros:** Fixes an existing accessibility violation. `--fg-muted` passes at 4.63:1. One-line CSS change.

**Cons:** Slightly darker article count label — minor visual change. Low urgency for a personal self-hosted tool.

**Context:** Discovered during `/plan-design-review` for the streak counter feature (2026-07-01). The streak counter was fixed in the same session (uses `--fg-muted` from the start). The `.feed-count` fix was deferred. File: `templates/base.html:679`.

**Depends on / blocked by:** Nothing.

---

## Feature Backlog

### [STREAK] User timezone support for streak day boundaries

**What:** Add a `timezone` field to `user_profiles`. Use it in `update_reading_streak()` to determine the local date instead of relying on PostgreSQL `CURRENT_DATE` (which uses the server/UTC timezone).

**Why:** A user in UTC+2 who reads at 11:00pm local (9:00pm UTC) on day N gets the streak correctly. But a user reading at 11:30pm local (9:30pm UTC on day N, but already day N+1 UTC) may or may not get credited, depending on server timezone. For a personal tool on a local NAS (likely same timezone as user), this is low risk — but worth fixing before sharing with family members in other timezones.

**Context:** Raised during `/plan-eng-review` (2026-07-01). Schema decision: `reading_streak` on `user_profiles`, 3 columns. Deferred as a TODO.

**Depends on / blocked by:** Migration 035 (reading_streak columns).

---

### [OPS] Streak visibility in ops dashboard

**What:** Add a streak column (or section) to the user activity view in the ops dashboard at `http://localhost:5001`.

**Why:** The ops dashboard currently shows user activity but no reading streak data. Once the streak feature ships, monitoring whether it's driving daily returns requires checking the DB manually or via raw SQL. A simple column in the users table view (current_streak, longest_streak, last_read_date) would make this visible at a glance.

**Context:** Raised during `/plan-eng-review` (2026-07-01). The ops dashboard is a separate Flask service (`app_ops/`). Deferred as a TODO.

**Depends on / blocked by:** Migration 035 (reading_streak columns).
