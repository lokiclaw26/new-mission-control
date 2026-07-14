# Mission Control v2 — Changelog

## v1.15.0 — 2026-07-15 — Dashboard polish & order workflow

Visual QA pass on 2026-07-15 identified 6 issues across the overview, sidebar,
project table, action list, and pending-orders section. All addressed.

### Fixed

- **Overview grid asymmetric** — `.summary-grid` switched from `auto-fit/minmax(180px, 1fr)`
  to a fixed 6-column `repeat(6, minmax(0,1fr))` at ≥1100px with two responsive
  breakpoints (1100px → 3-col, 760px → 2-col). All six cards (Hermes / Active /
  Failed / Warnings / Current Project / Last Check) now align in a single row.
- **Current Project self-reference** — Overview card now detects when the
  reporting path resolves to mission-control itself (`isSelfRef = pv.includes('mission-control')`)
  and renders `—` with a "self-reference hidden" tooltip instead of duplicating
  the dashboard as the active project.
- **Sidebar nav contrast** — `--text2` bumped `#8b949e → #b7c0cb`, `--text3` bumped
  `#6e7681 → #aab2bd` to clear WCAG AA against the `--panel #161b22` background.
- **Action Required missing fix-order action** — every warning / stale / fail row
  now ends with a "Send fix order" (or "Send fix order to Thor" for warnings) button
  wired to the existing dispatch pipeline. Agents no longer need to retype the
  project name in chat.
- **Projects table approval was read-only** — `YES` cell for `diy-hub-v1` is now a
  clickable `<button class="approve-btn">YES</button>` with hover / disabled states
  and `aria-pressed` toggle. Other rows continue to show static `no` text.
- **Pending orders had no in-page action** — each pending order now shows three
  buttons: `[▶ Dispatch]` `[✓ Approve]` `[✗ Reject]`. Front-end POSTs to
  `/api/data/order/decision` (new endpoint, see serve.py). Backend validates
  `decision ∈ {dispatched, approved, rejected}`, appends `event_type=order_decision`
  to `events.jsonl`, returns `{ok: true, decision, decided_at}`. The chat-gate
  safety notice is preserved at the top of the section.

### Not bugs (confirmed)

- **Last-24h bars & event-ID cropping** — these were flagged but the dashboard
  does not contain a "Recent activity" histogram section; event IDs in
  Logs/Health are rendered in full (e.g. `forge-MC-DISPATCH-FIX-ORDER-1`).
  No change needed.

### Verification

- Live at `http://127.0.0.1:8767/` (PID 1665293, port 8767 — local LAN).
- Endpoint smoke-test: `POST /api/data/order/decision` returns 200 + appends to
  events log when given `{order_id, decision}`.
- Visual proof: `docs/screenshots/v1.15.0-*.png` (4 captures: overview grid,
  sidebar contrast, approval button, orders panel).

### Files changed

- `code/mission-control.html` — 6 front-end fixes (CSS + render fns + click
  handlers).
- `code/serve.py` — new `POST /api/data/order/decision` handler in `do_POST`.
