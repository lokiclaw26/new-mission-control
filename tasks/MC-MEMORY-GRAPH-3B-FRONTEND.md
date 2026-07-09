---
task_id: MC-MEMORY-GRAPH-3B-FRONTEND
assigned_to: forge
title: Memory Graph 3B — fix canvas reset every 5s + node selection + responsive + clean inspector
type: bugfix
priority: high
status: done
kanban_status: done
assignee: forge
argus_passed: true
completed: 2026-06-17T19:45:00+04:00
created: 2026-06-17T19:30:00+04:00
created_by: thor
approval_required: false
---

## Context (NOFI 2026-06-17 ~19:30 Dubai)

NOFI reported: "why the memory graph jumps and resets every 5 seconds .. FIX IT"

Three distinct root causes in `code/memory-graph.html`:

1. **Canvas reset on poll** — `applyFilters()` is called inside `fetchGraph()` on every 5s tick. `applyFilters()` calls `Graph.graphData({...})` which restarts the d3-force simulation. Result: every 5s the camera/positions snap back to cold-start state → user sees "jump and reset".
2. **Selected node lost on poll** — when filter excludes the selected node, the filtered set no longer contains it → `graphData()` drops it from the graph → `selectedNode` reference becomes stale.
3. **No resize handling** — `graph-container` is `flex: 1` but `Graph` is initialized once with no ResizeObserver. Window resize = canvas stays at 1280x720 and overflows.

## Scope (frontend only, NO backend changes)

### Fix 1: Stop the 5s reset (PRIMARY)
- Initialize graph ONCE on page load.
- On each `fetchGraph()` poll: compute new filtered set, but **only call `Graph.graphData({...})` when the id set actually changed** (use a Set diff of node ids).
- When the set DID change: pass forward previous `x/y/z/vx/vy/vz` for nodes that survived the diff (extract from `Graph.graphData()` BEFORE the update), so the simulation continues from where it was — no snap-back.
- When the set did NOT change: skip `graphData()` entirely. Just update the footer counts + last-updated text.
- Use `Graph.d3ReheatSimulation()` only when NEW nodes are added, not on identity-stable updates.

### Fix 2: Preserve selected node across polls
- On every poll: check if `selectedNode` is still in the filtered set.
- If yes: keep selection. Update inspector only if metadata changed.
- If no: clear `selectedNode` to null and show empty placeholder.

### Fix 3: Canvas resize
- Add `ResizeObserver` on `.graph-container`.
- On resize: call `Graph.width(el.clientWidth).height(el.clientHeight)`. Debounce 200ms.

### Fix 4: Responsive layout
- `@media (max-width: 900px)`: controls + right-panel become collapsible drawers; sidebar becomes top bar with hamburger toggle.
- On mobile (≤600px): graph takes full visible area; no horizontal overflow at 390x844.

### Fix 5: Clean inspector
- Stop dumping raw node object as `<pre>JSON.stringify(node)</pre>` — leaks `__threeObj`, `x/y/z`, `vx/vy/vz`, geometry, material.
- Build inspector with DOM construction (textContent) showing: label, id, kind (colored badge), summary, status, importance, confidence, tags (chips), created/updated (formatted), project/path/url if present.
- Use only `textContent` + `document.createElement`. No `innerHTML` for user data.

### Fix 6: Filtering UX
- Footer shows `Nodes: <filtered> / <total>` and `Edges: <filtered> / <total>`.
- If filtered set is empty: show empty-state overlay: "No nodes match current filters."
- Clear `selectedNode` if filtered out.

## Constraints
- HTML only — no new JS frameworks, no new vendor files.
- Use 3d-force-graph + three already vendored at `code/vendor/`.
- Preserve all current endpoints + auth behavior (no backend changes).
- `start-mc.sh` behavior unchanged.
- No new files in `code/` unless needed.

## Verification (Argus)
1. Open `/memory-graph` in Playwright. Wait 20s. Confirm: NO jump, NO reset. Camera stays stable.
2. Click a node. Wait 20s. Confirm: inspector shows clean details, selection persists.
3. Reload at 390x844. Confirm: no horizontal overflow, controls collapsible, graph fills space.
4. Resize to 1280x720. Confirm: graph fills cell, no overlap.
5. Search with no matches. Confirm: empty-state overlay, footer shows `Nodes: 0 / N`.
6. Open inspector. Confirm: NO `__threeObj`, NO `x/y/z`, NO `vx/vy/vz` in rendered output.
7. `python -m py_compile code/*.py` — pass.
8. `python -m unittest discover` — 65/65 pass (no backend changes).

## Deliverables
- Patched `code/memory-graph.html`
- Log at `logs/2026-06-17-mc-memory-graph-3b-frontend.md`
- Commit + push to `main`
- 6 Playwright screenshots at `/tmp/mc-mg3b-*.png`
- Argus report at `qa/2026-06-17-mc-memory-graph-3b-frontend.md`
