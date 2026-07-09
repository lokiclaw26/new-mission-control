---
task_id: MC-MEMORY-GRAPH-2
assigned_to: forge
title: Memory Graph 2 — upgrade 2D Canvas to true 3D WebGL force graph (3d-force-graph + Three.js)
type: feature
priority: high
status: done
kanban_status: done
assignee: forge
argus_passed: true
completed: 2026-06-17T17:28:00+04:00
created: 2026-06-17T17:00:00+04:00
created_by: thor
approval_required: true
depends_on: [MC-MEMORY-GRAPH-1]
---

## Context (NOFI 2026-06-17 ~17:00 Dubai)

MC-MEMORY-GRAPH-1 shipped a 2D Canvas force-directed graph at `/memory-graph`. NOFI wants it upgraded to a **true 3D WebGL graph** using `3d-force-graph` (Three.js underneath). Vanilla JS, no React.

## Technical decisions (LOCKED — don't re-decide)

1. **Library: `3d-force-graph`** (NOT `react-force-graph-3d` — no React in MC)
   - Source: https://github.com/vasturiano/3d-force-graph
   - License: MIT
   - Version: pin to a specific known-good version (suggest 1.77.x or latest stable)
   - Underlying: Three.js (WebGL)
   - Vanilla compatible
2. **Distribution: vendor locally** (not CDN) — MC is local-first. The library files go into `01_projects/mission-control/code/vendor/3d-force-graph/` so `/memory-graph` works offline on the LAN.
3. **Persistence & backend: unchanged from MC-MEMORY-GRAPH-1.** Same endpoints, same JSONL log, same redactor, same event contract.
4. **Live updates: 5s polling** (already working, keep it). SSE optional enhancement.
5. **Page route, sidebar nav, dark/gold theme: unchanged.**

## Required actions

### Forge: 8 phases

#### Phase A: Vendor the library
Download and pin locally:
- `3d-force-graph` UMD/IIFE build (the standalone browser bundle, NOT the ESM one used by build tools)
- `three` (Three.js, the underlying renderer)
- `three/examples/jsm/` modules `OrbitControls` (for camera control) if 3d-force-graph doesn't bundle its own

How to get them:
```bash
mkdir -p /home/nofidofi/NofiTech-Ind/01_projects/mission-control/code/vendor/3d-force-graph
mkdir -p /home/nofidofi/NofiTech-Ind/01_projects/mission-control/code/vendor/three
# Use curl to download specific known-good versions
# 3d-force-graph standalone build: https://unpkg.com/3d-force-graph@1.77.0/dist/3d-force-graph.min.js
# Three.js: https://unpkg.com/three@0.160.0/build/three.min.js
# OrbitControls: https://unpkg.com/three@0.160.0/examples/js/controls/OrbitControls.js
```

**Critical:** the 3d-force-graph browser bundle expects `THREE` to be a global. Load order: three.min.js FIRST, then OrbitControls.js, then 3d-force-graph.min.js.

Save them in `vendor/three/three.min.js`, `vendor/three/OrbitControls.js`, `vendor/3d-force-graph/3d-force-graph.min.js`.

Update memory-graph.html to load them with `<script src="vendor/...">` tags BEFORE the inline app code.

#### Phase B: Rewrite the graph renderer
Replace the 2D Canvas force-directed code with `ForceGraph3D()`:

```javascript
const Graph = ForceGraph3D()(document.getElementById('graph'))
  .backgroundColor('#0a0a0a')  // match dark theme
  .nodeId('id')
  .nodeLabel(n => n.label || n.id)
  .nodeColor(n => KIND_COLORS[n.kind] || '#888888')
  .nodeVal(n => 1 + (n.importance || 0) * 8)
  .nodeRelSize(4)
  .linkSource('source')
  .linkTarget('target')
  .linkColor(l => 'rgba(212, 175, 55, 0.4)')
  .linkWidth(l => (l.weight || 0.5) * 2)
  .linkDirectionalParticles(l => l.active ? 4 : 0)  // animated particles for active edges
  .linkDirectionalParticleSpeed(0.006)
  .linkDirectionalParticleColor(() => '#d4af37')
  .onNodeClick(n => { selectedNode = n; renderInspector(); });
```

#### Phase C: Data mapping
The library expects `{nodes: [{id, ...}], links: [{source, target, ...}]}`. Our backend returns `{nodes, edges}`. **Map `edges` → `links` in the JS** before passing to the library.

For nodes:
- id → id
- kind → use KIND_COLORS lookup
- importance (0..1) → size via nodeVal
- label → label

For links/edges:
- source → source
- target → target
- weight → linkWidth
- kind → use a different color or just keep gold
- "active" edges (kind=created_from, used_tool, edited_file, caused_by) → directional particles ON

#### Phase D: Camera controls
3d-force-graph provides built-in OrbitControls via Three.js. Should work out of the box. Configure:
- Initial position: `{x: 0, y: 0, z: 200}` (zoom out so user sees the full graph)
- Initial rotation: slight tilt so depth is visible
- User can drag to orbit, scroll to zoom, right-click to pan

#### Phase E: Preserve all existing panels
Keep (don't break):
- Left controls panel: search, 11 kind checkboxes, importance slider, reset button
- Right panel: event feed + selected node inspector
- Header with live status dot
- Footer with node/edge counts
- Sidebar nav with 3 tabs
- 5s polling for graph + events
- Click-to-inspect (raycast through 3D)
- Search filter: when user types, fade unrelated nodes (or hide)
- Kind filter: hide non-matching
- Importance slider: hide nodes below threshold

When filters change, the graph should update WITHOUT resetting the camera position. To achieve this: don't recreate the Graph object, just call `Graph.nodeColor(...)` with a function that returns null/transparent for hidden nodes. Or rebuild with a "filtered" dataset and use a different set of nodes.

Simplest approach: rebuild the graph data on filter change, but reuse the camera position by saving/restoring it:
```javascript
const pos = Graph.cameraPosition();
Graph.graphData(filteredData);
Graph.cameraPosition(pos.x, pos.y, pos.z);
```

#### Phase F: Fix known issues from MC-MEMORY-GRAPH-1
1. **ghp_ redaction threshold:** in `redact_secrets()` in serve.py, lower the minimum length from 16 to 8 chars. Pattern: `gh[pousr]_[A-Za-z0-9]{8,}` (8 or more chars). Test with `ghp_shorttest` and `ghp_abcdef123456` — both should be redacted.

2. **Remove test nodes from default graph:** The 4 test nodes from MC-MEMORY-GRAPH-1 verification (`test-argus-1`, `test-secret-1`, `has secret`, `test-cli-helper`) are in the JSONL log. The user wants them out of the visible graph. Approach:
   - Add an admin endpoint `POST /api/memory-graph/cleanup-test-nodes` that removes nodes whose id starts with `test-`
   - Call it on next startup (one-time migration)
   - Or: just delete them from the existing memory-graph.json file directly via a script

3. **Reset should restore clean sample data:** the reset endpoint should restore from `sample-graph.json`, not just clear the file. Modify `reset_graph()` to copy sample-graph.json's contents over memory-graph.json.

4. **Don't re-add test nodes on future verification:** when Argus/Forge tests the system, use a separate test-namespace prefix (e.g. `verify-foo-1`) AND have a cleanup step that removes them after the test. OR: tests can use ephemeral nodes that auto-expire.

#### Phase G: Verification
- All existing endpoints still work
- New feature works: 3D graph, orbit, zoom, click
- Filter/search/slider work
- Event ingest still works
- Redaction test: `ghp_shorttest` and `ghp_abcdef123456` both redacted
- Playwright behavioral: load page, wait 5s, screenshot, verify WebGL canvas is non-empty (the 3D library creates a `<canvas>` element)
- Take 2 screenshots: one default view, one after a programmatic camera rotation (to prove 3D)
- Click a node via Playwright, verify inspector updates

#### Phase H: Documentation
Add a section to `MEMORY_GRAPH.md` (or create if not exists):
- Library: 3d-force-graph v1.77.x + Three.js v0.160.x
- License: MIT
- Source: https://github.com/vasturiano/3d-force-graph + https://threejs.org
- Vendored path: `01_projects/mission-control/code/vendor/`
- Why vendored: MC is local-first, no CDN at runtime
- Update instructions: re-download with curl from unpkg

### Out of scope
- DO NOT use React
- DO NOT use a CDN at runtime (vendor locally)
- DO NOT change the event contract
- DO NOT change the backend routes
- DO NOT change the JSONL log format
- DO NOT add cron
- DO NOT add new features beyond the 3D upgrade + the 4 known-issue fixes
- DO NOT touch the kanban page
- DO NOT touch roguelike or DIY Hub

### Argus: verify
- [ ] `/` 200
- [ ] `/kanban` 200
- [ ] `/memory-graph` 200
- [ ] Page contains a WebGL canvas (not 2D)
- [ ] Graph has visible 3D depth (orbit/zoom works)
- [ ] All controls still in their panels (left, right, header, footer)
- [ ] 11 kind filters present
- [ ] Importance slider present
- [ ] Search input present
- [ ] Reset button present
- [ ] Event feed populated
- [ ] Inspector visible (with "Click a node to see details")
- [ ] Live status dot present
- [ ] Footer metrics: nodes, edges, last updated
- [ ] Sidebar nav: 3 tabs
- [ ] Click a node → inspector updates
- [ ] Drag the canvas → camera orbits (test with Playwright mouse events)
- [ ] POST a node event → appears in graph
- [ ] POST an edge event → link appears
- [ ] Redaction test: `sk-...` redacted
- [ ] Redaction test: `ghp_shorttest` redacted (NEW — was missing before)
- [ ] Redaction test: `ghp_abcdef123456` redacted
- [ ] Redaction test: `Bearer ...` redacted
- [ ] Redaction test: `Authorization: ...` redacted
- [ ] Redaction test: `api_key=...` redacted
- [ ] Redaction test: `token=...` redacted
- [ ] No console errors
- [ ] Test nodes from MC-MEMORY-GRAPH-1 removed from default graph
- [ ] Reset button restores clean sample data
- [ ] 2 screenshots saved (default + rotated)

## Final report format

```
MC-MEMORY-GRAPH-2 — 3D UPGRADE REPORT

STATUS: Verified / Partial / Failed

LIBRARY:
- name: 3d-force-graph
- version: x.y.z
- license: MIT
- source: https://github.com/vasturiano/3d-force-graph
- underlying: three.js vX.Y.Z
- vendored: yes — path
- why: <one line>

CHANGED FILES:
- list with one-line description

3D FEATURES:
- real x/y/z positioning: yes
- orbit: yes (Three.js OrbitControls)
- zoom: yes
- pan: yes
- click to inspect: yes
- hover labels: yes
- directional particles for active edges: yes
- node size = importance: yes
- node color = kind: yes
- link opacity = weight: yes

PRESERVED:
- /memory-graph route: yes
- sidebar nav 3 tabs: yes
- all 6 backend endpoints: yes
- event contract: yes
- JSONL log: yes
- 5s polling: yes
- all UX panels: yes

BUG FIXES (from MC-MEMORY-GRAPH-1):
- ghp_ threshold lowered: yes (16 → 8)
- test nodes removed: yes
- reset restores sample data: yes
- no verification nodes in default graph: yes

SAFETY:
- 7 redaction patterns tested: list each result
- no leaks: yes/no

VERIFICATION:
- / 200
- /kanban 200
- /memory-graph 200
- WebGL canvas present: yes
- orbit works: yes
- zoom works: yes
- click works: yes
- filters work: yes
- search works: yes
- importance slider works: yes
- event ingest: yes
- redaction: 7/7 patterns
- no console errors: yes

SCREENSHOTS:
- default view: path
- rotated view: path
- selected node: path
- event ingest: path

ARGUS: Pass / Fail + reason

GIT: commit SHA

NOT INCLUDED (per spec):
- React: not used
- CDN: not used (vendored)
- new endpoints: none (only the cleanup-test-nodes admin endpoint as a small addition)
- new event types: none

LIMITATIONS:
- list

NEXT:
- list
```

## Notes for Forge

- **3d-force-graph v1.77.x is a known-good version** that ships an IIFE/UMD build compatible with vanilla JS. The dist file is `3d-force-graph.min.js` and expects `THREE` global.
- **Three.js v0.160.x** is compatible with the 3d-force-graph 1.77 release line. Use `three.min.js` (build/ folder) + `OrbitControls.js` (examples/js/ folder, NOT examples/jsm — those are ESM).
- **Load order matters**: three.min.js → OrbitControls.js → 3d-force-graph.min.js → your inline app code.
- **If 3d-force-graph fails to load or init**, fall back to a simple Three.js scene (sphere for each node, lines for edges) — but the library should work.
- **For the click-to-inspect test in Playwright**: 3d-force-graph uses Three.js's raycaster. Clicking the canvas at a node's projected screen position should trigger the onNodeClick handler. With Playwright, find the projected screen position of a known node by reading Graph.graphData() then computing the projection.
- **For the orbit test in Playwright**: simulate a mouse drag on the canvas (mousedown → mousemove → mouseup) and verify the camera position changed.
- **When changing filter/search/slider**, save the camera position, rebuild the graph data, restore the camera position. This is the standard pattern.

## Dependencies documentation

After vendoring, add to `01_projects/mission-control/docs/MEMORY_GRAPH.md`:

```markdown
## Frontend dependencies (vendored)

The 3D graph uses two open-source libraries, both vendored locally for offline-first operation:

| Library | Version | License | Source | Path |
|---------|---------|---------|--------|------|
| 3d-force-graph | 1.77.x | MIT | https://github.com/vasturiano/3d-force-graph | `code/vendor/3d-force-graph/` |
| three.js | 0.160.x | MIT | https://threejs.org | `code/vendor/three/` |

Both are loaded via local `<script>` tags, not a CDN. Mission Control works offline on the LAN.

To update:
```bash
curl -o code/vendor/3d-force-graph/3d-force-graph.min.js https://unpkg.com/3d-force-graph@1.77.0/dist/3d-force-graph.min.js
curl -o code/vendor/three/three.min.js https://unpkg.com/three@0.160.0/build/three.min.js
curl -o code/vendor/three/OrbitControls.js https://unpkg.com/three@0.160.0/examples/js/controls/OrbitControls.js
```
```
