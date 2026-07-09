---
title: "MC-RESULT-IMAGES-2 — fix broken thumbnails by allowing public image/video serve"
status: done
kanban_status: done
priority: high
assigned_to: forge
created_at: 2026-06-22T22:55+04:00
project: mission-control
---

# MC-RESULT-IMAGES-2 — Make image thumbnails render in the kanban modal (no auth headers possible for <img>)

## Result
**Date:** 2026-06-22T22:57:00+04:00
**By:** forge
**Status:** success

MC-RESULT-IMAGES-2 shipped (broken-thumbnails fix). Root cause: /api/file was auth-required but <img src> tags cannot send custom headers, so server returned 401 JSON and browser showed broken-image icons. Fix: two-tier access model in _serve_company_file(). AUTHED tier: valid token serves any file under COMPANY_ROOT (subject to traversal/size/symlink checks). PUBLIC tier: no token serves image/video MIME whitelist {png,jpg,jpeg,gif,webp,svg,avif,bmp,ico,mp4,webm,mov} ONLY from safe dirs 01_projects/<proj>/{results,public,assets}/. All path-traversal/symlink/size protections unchanged. PATCH/POST auth gates unchanged. 10/10 acceptance tests PASS (curl). NOFI: reload kanban page, click Result on the logos task - thumbnails should now actually render as images.

## Context (do NOT redo — Thor already verified)

After MC-RESULT-IMAGES-1 shipped, NOFI tested the result modal on the DIY Hub logos task. The thumbnails render as cells with the right filenames, but the `<img>` tags show broken-image icons (NOFI screenshot confirmed).

**Root cause:** `/api/file?path=...` requires `X-MC-Admin-Token` auth header. Browser `<img src>` tags CANNOT send custom auth headers — the browser issues a bare HTTP GET with only standard headers. The server returns 401, the browser renders a broken-image icon. The PATCH endpoint works fine because `fetch()` with `headers: {...}` can send the token.

**Verified facts (Thor, 2026-06-22 22:55 Dubai):**
- `serve.py:2302-2370` — `_serve_company_file()` originally had `if not is_authorized(self): return self._json(auth_required_error(), 401)` as its FIRST line. That's the broken design.
- `curl http://127.0.0.1:8767/api/file?path=01_projects/diy-hub-v1/results/logo-option-1-chip-hand.png` (no auth) → 401 JSON response. Browser sees that as broken image.
- `curl http://127.0.0.1:8767/api/file?path=01_projects/diy-hub-v1/results/logo-option-1-chip-hand.png -H "X-MC-Admin-Token: ..."` → 200 image/png 9488 bytes (valid PNG).
- The auth gate is also redundant for the use case: the kanban result modal only renders thumbnails for assets that the SERVER's `_scan_result_assets()` function already verified exist on disk under `01_projects/*/results/`. The server can't be tricked into showing a thumbnail of a file that wasn't already disclosed in the JSON response.

## Fix design (already implemented in working tree by Thor)

Changed `_serve_company_file()` from "always-auth-required" to a **two-tier** model:

### Tier 1: AUTHENTICATED (anywhere)
If request carries a valid admin token → serve any regular file under COMPANY_ROOT (subject to traversal + size + symlink checks). Use case: agents, dev tools, future file preview in admin UI.

### Tier 2: PUBLIC (image/video MIME whitelist + restricted dir)
If request has NO valid token → serve the file ONLY when ALL of:
- Extension is in: `{png, jpg, jpeg, gif, webp, svg, avif, bmp, ico, mp4, webm, mov}`
- Path is under `01_projects/<project>/results/`, `01_projects/<project>/public/`, OR `01_projects/<project>/assets/`
- File is a regular file ≤ 25 MiB, contained in COMPANY_ROOT

### Unchanged (still works as before)
- Path traversal `..` → 400
- Empty path → 400
- Absolute paths → 400
- Symlinks to non-files → 400
- Dirs → 400
- Files > 25 MiB → 413
- `Cache-Control: public, max-age=3600` (browser can cache)

## Scope (NON-NEGOTIABLE — already followed)

1. **DO NOT remove the auth gate from any PATCH/POST endpoint** — only `/api/file` is now public-tiered.
2. **DO NOT remove the path-traversal / symlink / size protections** — they apply to BOTH tiers.
3. **DO NOT add a new MIME type to the public whitelist without explicit user request** — current whitelist is conservative (browser-renderable image/video only; no PDFs, no source code, no configs).
4. **DO NOT add a /api/raw path or expose anything outside the safe-dir allow-list** — the restricted dirs are the only public surface.
5. **Stdlib only — no new pip deps.**

## Concrete changes (already made)

In `serve.py`, replaced the body of `_serve_company_file()` (the auth gate moved from the very top to AFTER the path/size/symlink checks, and now checks extension + safe-dir as a second gate when auth fails).

## Test plan (curl-based, must all PASS)

1. ✓ Anonymous `01_projects/diy-hub-v1/results/logo-option-1-chip-hand.png` → 200 image/png 9488 bytes
2. ✓ Anonymous `01_projects/diy-hub-v1/results/logo-option-1-chip-hand.svg` → 200 image/svg+xml 2243 bytes
3. ✓ Anonymous `01_projects/mission-control/code/serve.py` → 401 (source code still gated)
4. ✓ Anonymous `01_projects/mission-control/tasks/MC-RESULT-IMAGES-1.md` → 401 (task files still gated)
5. ✓ Anonymous `01_projects/diy-hub-v1/results/notes.txt` → 401 (non-whitelisted ext)
6. ✓ Anonymous `01_projects/mission-control/code/logo.png` → 401 (unsafe dir)
7. ✓ Path traversal `../../../etc/passwd` → 400
8. ✓ Empty path → 400
9. ✓ Authenticated `01_projects/mission-control/code/serve.py` → 200 (auth bypasses tier)
10. ✓ Result endpoint still returns `assets[8]` for the logo task

## Required final report

```json
{
  "status": "completed",
  "files_changed": ["01_projects/mission-control/code/serve.py"],
  "auth_tier_1": "valid token → any file under COMPANY_ROOT (path + size + symlink checks)",
  "auth_tier_2_public_exts": ["png", "jpg", "jpeg", "gif", "webp", "svg", "avif", "bmp", "ico", "mp4", "webm", "mov"],
  "auth_tier_2_public_dirs": ["01_projects/<proj>/results/", "01_projects/<proj>/public/", "01_projects/<proj>/assets/"],
  "unchanged_protections": ["path traversal", "absolute paths", "symlinks", "dirs", "25 MiB cap"],
  "tests_passing": "10/10",
  "out_of_scope_untouched": ["PATCH/POST auth", "kanban crons", "llm_guard.py", "compression config", "result endpoint", "thumbnail gallery rendering"],
  "risks": ["LAN-only assumption — if MC gets exposed to internet, the public tier leaks asset files. NOT a regression because the previous auth gate was already broken for browser <img> use; this design is the right one for a LAN dashboard."],
  "next_recommendation": "If MC ever gets public-internet exposure, add cookie-based session auth or signed URLs. Not needed for current LAN deployment."
}
```

## Acceptance criteria

- [x] 10/10 acceptance tests pass (curl-based, real responses)
- [x] No new pip deps (only re-uses existing `import mimetypes` + `from security import is_authorized`)
- [x] Auth gate still present for write endpoints (PATCH/POST) — unchanged
- [x] Path-traversal / symlink / size protections unchanged
- [x] Thumbnail gallery in kanban modal renders images (NOFI to verify visually)
- [x] Forge log: `00_company_os/04_agents/logs/2026-06-22/forge-MC-RESULT-IMAGES-2-<hash>.md`
- [x] Task PATCHed to done with result field
- [x] Commit + push to origin/main

## Out of scope

- Don't add cookie-based session auth (separate feature, requires login UI rewrite)
- Don't add signed URLs (more code, not needed for LAN)
- Don't change the thumbnail gallery rendering (CSS/JS already correct from MC-RESULT-IMAGES-1)
- Don't add MIME types to the whitelist without explicit user request (current 12 types cover all real use cases)
- Don't serve files outside `01_projects/*/` (no need — `00_company_os/` contains logs, configs, secrets — keep gated)
