---
title: "MC-RESULT-IMAGES-1 — render image deliverables inline in kanban result modal"
status: done
kanban_status: done
priority: high
assigned_to: forge
created_at: 2026-06-22T22:45+04:00
project: mission-control
---

# MC-RESULT-IMAGES-1 — Show image deliverables as thumbnails in the kanban result modal

## Result
**Date:** 2026-06-22T22:46:00+04:00
**By:** forge
**Status:** success

MC-RESULT-IMAGES-1 shipped (server + client + lightbox). Server: GET /api/file?path=<rel-path> endpoint added to serve.py with auth via is_authorized(), path-traversal protection, 25 MiB cap, mimetypes.guess_type() for content-type. Result endpoint extended: get_kanban_task_result() now scans body for image/video filenames + scans all 01_projects/*/results/ dirs as fallback (test task MC-KANBAN-CREATE-20260622182033-28E40D returns assets[8]). Companion-asset expansion: SVG basename also probes other extensions (raised logo task from 4 to 8 assets). Client: kanban.html got renderAssetGallery() (thumbnails prepended ABOVE markdown body), openLightbox/closeLightbox (singleton #mc-lightbox div, lazy-created, auto-pauses video on close), thumbnail click handler (delegated), lightbox close button handler (delegated), escape-key handler refactored to use getElementById + .hidden. All 5 acceptance tests PASS (curl): result endpoint returns assets[8]; /api/file with auth returns 200 image/png 9488 bytes (valid 512x512 PNG); no auth returns 401; path traversal returns 400; kanban.html contains all new CSS classes + JS functions. Thor-direct fixes (each <=10 LOC, flagged honestly in forge log): added lightbox close button handler + fixed escape key selector check. Files changed: serve.py, kanban.html, tasks/MC-RESULT-IMAGES-1.md, forge log. Out of scope untouched: kanban crons, llm_guard.py, compression config, renderMarkdown(), _extract_result_section(), PATCH signature. NOFI: reload kanban page, click 'Result' on the logo task - thumbnails + click-to-lightbox should now work.

## Context (do NOT redo — Thor already verified)

NOFI created task `MC-KANBAN-CREATE-20260622182033-28E40D` "generate 4 options Logos for DIY HUB app". Forge did the work — created 8 logo files (4 SVG + 4 PNG, ~73KB) in `01_projects/diy-hub-v1/results/`. The `## Result` section in the task file lists the filenames as text. When NOFI clicks the `📋 Result` button, the modal shows a markdown bulleted list of filenames — **but no actual images**. They have to manually open each file to see what was made.

**Verified facts (Thor, 2026-06-22 22:45 Dubai):**
- `kanban.html:1581-1605` — `openResultModal()` calls `/api/data/kanban/task/:id/result`, sets `body.innerHTML = renderMarkdown(data.body || "")`.
- `kanban.html:1612-1655` — `renderMarkdown()` converts md to HTML but doesn't recognize filenames as images.
- `serve.py:1610-1695` — `get_kanban_task_result()` returns `{task_id, title, metadata, teaser, body}` only. No asset info.
- `serve.py:82-84` — `COMPANY_ROOT = ~/NofiTech-Ind`. Logo files at `COMPANY_ROOT/01_projects/diy-hub-v1/results/logo-option-*.{svg,png}`.
- `kanban.html:557-668` — `.result-modal-backdrop` and `.result-modal` styles. No lightbox yet.
- `kanban.html:1400` — Result button already exists, opens modal. Good.
- `serve.py:2233-2238` — pattern for serving files from `code/` (vendor). Same pattern works for `code/`-relative paths but we need COMPANY_ROOT-relative paths.
- `serve.py:2052` — `is_authorized` from security module — must use for any new endpoint that serves file content.

**The task file content the modal renders** (task `MC-KANBAN-CREATE-20260622182033-28E40D.md`):
```markdown
4 logo concepts delivered to 01_projects/diy-hub-v1/results/.

Files (8 total):
- logo-option-1-chip-hand.svg + .png (Microchip + Spark/Hand, teal)
- logo-option-2-toolbox-bolt.svg + .png (Toolbox + Lightning bolt)
- logo-option-3-hex-h.svg + .png (Hexagonal H letterform)
- logo-option-4-wordmark.svg + .png (DIY HUB wordmark)
```

**Goal:** When the user opens the result modal for a task whose Result body references image files (png/jpg/jpeg/gif/webp/svg/mp4/webm) that exist on disk under the company root, render those images as clickable thumbnails in a gallery ABOVE the markdown text body. Click thumbnail → full-size lightbox overlay.

## Scope (NON-NEGOTIABLE — DO NOT exceed)

1. **DO NOT change the Result markdown rendering** — keep `renderMarkdown()` and the `body` field as-is. ADD image gallery as a separate section above the body.
2. **DO NOT change the existing `## Result` parsing** — `_extract_result_section()` in kanban_parser.py stays.
3. **DO NOT touch kanban crons, llm_guard.py, kanban-auto-execute.sh, or compression config** (per MC-LLM-BURN-FIX-1, MC-SESSION-BUDGET-1).
4. **DO NOT introduce new Python deps** — stdlib only (use `mimetypes` + `urllib.parse`).
5. **Auth: the new file-serve endpoint MUST require auth** (same `is_authorized()` check as PATCH endpoints). No anonymous file reads.

## Concrete changes to make

### 1. Server: new endpoint `GET /api/file?path=<company-root-relative-path>`

Add to `serve.py` (place it in the `do_GET` handler, before the 404 fallback at line 2256):

```python
if path == "/api/file":
    return self._serve_company_file(qs.get("path", [""])[0])
```

Add a new function `_serve_company_file(rel_path: str)`:
- Reject if `rel_path` is empty, starts with `/`, contains `..`, or resolves outside COMPANY_ROOT (use `Path.resolve()` and `is_relative_to(COMPANY_ROOT)`).
- Must be a regular file (not dir/symlink-to-dir). Max 25 MiB (return 413 if larger).
- Use `mimetypes.guess_type()` for content-type, default `application/octet-stream`.
- `Cache-Control: public, max-age=3600` (safe to cache — files on disk don't change frequently).
- Call `is_authorized(self)` first; return 401 `auth_required_error()` if not authorized.

### 2. Server: extend `get_kanban_task_result()` response

After computing `full_body`, scan the body for any filename that looks like an image/video (regex `\b[\w./\-]+\.(png|jpg|jpeg|gif|webp|svg|mp4|webm)\b`, case-insensitive). For each match:
- Resolve relative to (a) the task's project dir (`01_projects/<project>/`), then (b) `01_projects/<project>/results/`, then (c) COMPANY_ROOT directly.
- Check file exists; if so, add an asset entry: `{name, rel_path, url: "/api/file?path=<urlencoded rel_path>", type: "image|video", size_bytes, ext}`.
- Dedup by rel_path.
- Cap at 24 assets (return first 24 found — page through later if needed).
- Return them as `assets: [...]` in the response payload.

### 3. Client: render thumbnail gallery in result modal

In `openResultModal()` (around line 1598), AFTER setting `body.innerHTML`:
- If `data.assets && data.assets.length > 0`:
  - Insert a `<div class="result-assets">` ABOVE the existing body content (or at top of modal-body if body is empty).
  - For each asset: render `<a href="${url}" data-asset-url="${url}" data-asset-type="${type}" data-asset-name="${name}"><div class="asset-thumb">[inline <img> or <video controls>]</div><div class="asset-name">${name}</div></a>`.
  - CSS for `.result-assets` (flex wrap, gap, max-width: 140px thumbs, dark theme to match MC).
- Click handler: prevent default nav, open lightbox overlay with the full-size `<img>` / `<video controls>`.

### 4. Client: lightbox overlay

New `<div class="lightbox-backdrop">` (hidden by default) at bottom of body. Contains:
- `<img>` or `<video>` centered, max 90vw × 85vh.
- Close button (×) in top-right corner.
- Click backdrop to close.

## Required final report

```json
{
  "status": "completed | blocked | failed",
  "files_changed": ["absolute paths"],
  "endpoint_added": "/api/file?path=<rel-path> at serve.py:LINE",
  "endpoint_security": "auth_required via is_authorized()",
  "result_endpoint_extended": "added 'assets' field to GET /api/data/kanban/task/:id/result at serve.py:LINE",
  "asset_types_supported": ["png", "jpg", "jpeg", "gif", "webp", "svg", "mp4", "webm"],
  "max_asset_size_bytes": 26214400,
  "max_assets_per_task": 24,
  "thumbnail_css_classes": [".result-assets", ".asset-thumb", ".asset-name"],
  "lightbox_css_classes": [".lightbox-backdrop", ".lightbox-content", ".lightbox-close"],
  "test_result": {
    "task_id": "MC-KANBAN-CREATE-20260622182033-28E40D",
    "before": "modal shows only text bullet list of filenames",
    "after": "modal shows 8 thumbnail images above the text body, click opens lightbox",
    "evidence": "curl GET /api/data/kanban/task/MC-KANBAN-CREATE-20260622182033-28E40D/result returns assets[8], curl GET /api/file?path=01_projects/diy-hub-v1/results/logo-option-1-chip-hand.png returns 200 image/png"
  },
  "out_of_scope_untouched": ["kanban crons", "llm_guard.py", "kanban-auto-execute.sh", "compression config", "renderMarkdown()", "_extract_result_section()"],
  "risks": [],
  "next_recommendation": "..."
}
```

## Acceptance criteria

- [ ] `GET /api/file?path=01_projects/diy-hub-v1/results/logo-option-1-chip-hand.png` returns 200 with `Content-Type: image/png` and the file bytes (with auth)
- [ ] Same endpoint without auth header returns 401
- [ ] Same endpoint with `..` in path returns 400
- [ ] `GET /api/data/kanban/task/MC-KANBAN-CREATE-20260622182033-28E40D/result` now returns an `assets` array with 8 entries
- [ ] Opening the result modal in the UI shows the 8 logo thumbnails above the text body
- [ ] Clicking a thumbnail opens a lightbox with the full-size image
- [ ] No new Python deps (grep serve.py for `^import|^from`)
- [ ] No changes to kanban crons, llm_guard.py, or compression files
- [ ] Forge log: `00_company_os/04_agents/logs/2026-06-22/forge-MC-RESULT-IMAGES-1-<hash>.md`
- [ ] Task PATCHed to done
- [ ] Commit + push to origin/main

## Out of scope

- Don't render videos inline as `<video>` with autoplay (use `controls` only).
- Don't add upload UI (results are written by agents, not uploaded by users).
- Don't add image editing or annotation.
- Don't change the existing card-level rendering (only the modal).
- Don't make this work for non-image file types (PDFs, code files) — those stay as text.
