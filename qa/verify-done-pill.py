#!/usr/bin/env python3
"""
MC-KANBAN-DONE-PILL-1 verification (2026-06-19, forge).

Class 7 (visibility) check: DONE cards on the kanban must show a visible
green "DONE" pill (not a tiny grey dot), full opacity, at the top of the
Done column.

Three-layer test:
  L1 (data):  /api/data/kanban returns tasks with status=done AND
              kanban_status=done (i.e. the cascade worked).
  L2 (DOM):   .kanban-card[data-status=done] renders with the new
              .card-status-pill.status-done element.
  L3 (visible): getComputedStyle() on the pill confirms green border +
              green text, opacity 1.0 on the card, bounding box in viewport.

Saves 4 screenshots to qa/mc-kanban-done-pill-1/.
"""
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = "/home/nofidofi/.agent-browser/browsers/chrome-149.0.7827.54/chrome"
URL = "http://127.0.0.1:8767/kanban"
API = "http://127.0.0.1:8767/api/data/kanban"
OUT = Path(__file__).resolve().parent.parent / "qa" / "mc-kanban-done-pill-1"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    results = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
               "url": URL, "checks": []}
    failed = []

    def check(name, ok, detail=""):
        rec = {"name": name, "ok": bool(ok), "detail": detail}
        results["checks"].append(rec)
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        if not ok:
            failed.append(name)
        return ok

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROME,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            headless=True,
        )
        page = browser.new_page(viewport={"width": 2400, "height": 1400})
        # L1: data layer via API
        api = page.request.get(API)
        check("L1: API /api/data/kanban returns 200", api.status == 200,
              f"status={api.status}")
        board = api.json()
        # Find a done card
        done_tasks = []
        for col in board.get("columns", []):
            if col.get("id") == "done":
                done_tasks = col.get("tasks", [])
                break
        check("L1: Done column has tasks", len(done_tasks) > 0,
              f"count={len(done_tasks)}")
        all_status_done = all(t.get("status", "").lower() == "done" for t in done_tasks)
        all_kanban_done = all(t.get("kanban_status", "").lower() == "done" for t in done_tasks)
        check("L1: Every done card has status=done (cascade worked)",
              all_status_done,
              f"mismatched={sum(1 for t in done_tasks if t.get('status','').lower() != 'done')}")
        check("L1: Every done card has kanban_status=done",
              all_kanban_done,
              f"mismatched={sum(1 for t in done_tasks if t.get('kanban_status','').lower() != 'done')}")

        # L2 + L3: page render
        page.goto(URL, wait_until="networkidle", timeout=30000)
        page.wait_for_selector(".kanban-card", timeout=15000)
        # wait a beat for the smart render + heartbeat to finish
        page.wait_for_timeout(2000)

        # screenshot 1: full board
        page.screenshot(path=str(OUT / "01-full-board.png"), full_page=False)

        # find top done card
        top_done = page.query_selector("#kanban-col-done .kanban-card:first-child")
        check("L2: Top card in Done column is in the DOM", top_done is not None)
        if not top_done:
            browser.close()
            return _finalize(results, failed, OUT)

        # L2: pill exists
        pill = top_done.query_selector(".card-status-pill.status-done")
        check("L2: Done card has .card-status-pill.status-done element", pill is not None)
        if pill:
            pill_text = pill.inner_text().strip().lower()
            check("L2: Pill text contains 'done' (not 'in progress')",
                  "done" in pill_text,
                  f"pill_text={pill_text!r}")

        # L3: visibility
        opacity = page.evaluate(
            "el => getComputedStyle(el).opacity", top_done
        )
        check("L3: Done card opacity is 1.0 (not faded)",
              float(opacity) >= 0.99,
              f"opacity={opacity}")

        border_color = page.evaluate(
            "el => getComputedStyle(el).borderLeftColor", top_done
        )
        # green is #3fb950 -> rgb(63, 185, 80)
        check("L3: Done card border-left is green",
              "63, 185, 80" in border_color or "3fb950" in border_color.lower(),
              f"border-left-color={border_color}")

        if pill:
            pill_color = page.evaluate(
                "el => getComputedStyle(el).color", pill
            )
            pill_border = page.evaluate(
                "el => getComputedStyle(el).borderColor", pill
            )
            check("L3: Pill text color is green",
                  "63, 185, 80" in pill_color or "3fb950" in pill_color.lower(),
                  f"color={pill_color}")
            check("L3: Pill border color is green",
                  "63, 185, 80" in pill_border or "3fb950" in pill_border.lower(),
                  f"border={pill_border}")

        # L3: bounding box in viewport
        box = top_done.bounding_box()
        in_view = box and box["x"] >= 0 and box["y"] >= 0
        check("L3: Top done card is in the viewport (not scrolled off)",
              bool(in_view),
              f"bbox={box}")

        # screenshot 2: done column only
        done_col = page.query_selector("#kanban-col-done")
        if done_col:
            done_col.screenshot(path=str(OUT / "02-done-column.png"))
        # screenshot 3: top done card close-up
        top_done.screenshot(path=str(OUT / "03-top-done-card.png"))

        # regression: the other 5 columns still render
        for cid in ("triage", "todo", "ready", "running_now", "blocked"):
            col_el = page.query_selector(f"#kanban-col-{cid}")
            check(f"L2: Column {cid!r} still renders (regression)", col_el is not None)

        # screenshot 4: all 6 columns side-by-side
        page.screenshot(path=str(OUT / "04-all-six-columns.png"), full_page=False)

        browser.close()

    return _finalize(results, failed, OUT)


def _finalize(results, failed, out_dir):
    results["failed"] = failed
    results["verdict"] = "PASS" if not failed else "FAIL"
    (out_dir / "results.json").write_text(json.dumps(results, indent=2))
    print(f"\nVERDICT: {results['verdict']}  ({len(failed)} failed)")
    print(f"Results: {out_dir / 'results.json'}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
