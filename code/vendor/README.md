# Vendored frontend libraries (MC-MEMORY-GRAPH-2)

These two libraries are vendored locally so Mission Control runs offline on
the LAN with **no CDN at runtime**.

| Library        | Version  | License | Source                                                 | Path                            |
|----------------|----------|---------|--------------------------------------------------------|---------------------------------|
| 3d-force-graph | 1.77.0   | MIT     | https://github.com/vasturiano/3d-force-graph           | `vendor/3d-force-graph/`        |
| three.js       | 0.160.0  | MIT     | https://threejs.org                                     | `vendor/three/`                 |

## Load order (per MC-MEMORY-GRAPH-2 spec)

```html
<script src="vendor/three/three.min.js"></script>          <!-- sets window.THREE global -->
<script src="vendor/3d-force-graph/3d-force-graph.min.js"></script>  <!-- uses THREE, sets window.ForceGraph3D -->
```

## Note on OrbitControls

The MC-MEMORY-GRAPH-2 spec calls for loading
`vendor/three/OrbitControls.js` between the two scripts. As of three.js
r150 the `examples/js/controls/OrbitControls.js` file was removed (the
project moved to ESM `examples/jsm/controls/OrbitControls.js`).

3d-force-graph 1.77.0 ships its **own** bundled camera controls
(orbit / zoom / pan are handled internally by the library), so the
external `OrbitControls.js` file is not needed at runtime.

The vendored copy of `three.min.js@0.160.0` is loaded first so the
`window.THREE` global is available to the UMD bundle. The legacy
`build/three.min.js` shim is deprecated in r150+ but still ships in
0.160.0 and works.

## To update

```bash
curl -o code/vendor/3d-force-graph/3d-force-graph.min.js \
  https://unpkg.com/3d-force-graph@1.77.0/dist/3d-force-graph.min.js
curl -o code/vendor/three/three.min.js \
  https://unpkg.com/three@0.160.0/build/three.min.js
```
