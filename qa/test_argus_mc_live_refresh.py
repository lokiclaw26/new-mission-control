#!/usr/bin/env python3
"""
Argus QA test for MC-LIVE-REFRESH-1 (commit 60bf1f3) on the LIVE server :8767.

Runs all 8 checks from the task spec, saves screenshots, and writes a JSON
result blob that the markdown-log writer consumes.

Run:
    python3 /home/nofidofi/NofiTech-Ind/01_projects/mission-control/qa/test_argus_mc_live_refresh.py
"""
import json
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8767"
SCREENSHOT_DIR = Path("/home/nofidofi/.hermes/image_cache")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
RESULT_FILE = Path("/tmp/argus_mc_live_refresh_result.json")

CHROME_EXEC = "/home/nofidofi/.agent-browser/browsers/chrome-149.0.7827.54/chrome"

PANELS = [
    "1. Overview",
    "2. Agents",
    "3. Action Required",
    "4. Tasks",
    "5. Projects",
    "6. Logs / Health",
    "7. Warnings",
    "8. Pending Orders",
    "9. GitHub Connection",
]

results = {}


def http_get(path):
    req = urllib.request.Request(BASE + path, method="GET")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read().decode())


def http_post(path, body):
    req = urllib.request.Request(
        BASE + path,
        method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode())
        except Exception:
            payload = {}
        return e.code, payload


def shot(page, name):
    p = SCREENSHOT_DIR / f"argus-mc-live-refresh-{name}.png"
    page.screenshot(path=str(p), full_page=False)
    return str(p)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME_EXEC)
        # Use a separate context for the "fresh" page used in check 6 so we can
        # close it without affecting the main test page. We do most checks
        # against `page` then close it before the 130s age-out wait.

        context = browser.new_context(viewport={"width": 1400, "height": 1000})
        page = context.new_page()

        # =========================================================
        # 1. Auto-refresh works
        # =========================================================
        page.goto(BASE + "/", wait_until="networkidle")
        page.wait_for_function(
            "() => { const e = document.getElementById('last-refreshed'); return e && /\\d{2}:\\d{2}:\\d{2}/.test(e.textContent || ''); }",
            timeout=10000,
        )
        first_text = page.locator("#last-refreshed").text_content()
        m1 = re.search(r"(\d{2}):(\d{2}):(\d{2})", first_text or "")
        first_ts = int(m1.group(1)) * 3600 + int(m1.group(2)) * 60 + int(m1.group(3)) if m1 else -1
        shot_path_1_before = shot(page, "1-auto-refresh-before")
        time.sleep(7.5)
        second_text = page.locator("#last-refreshed").text_content()
        m2 = re.search(r"(\d{2}):(\d{2}):(\d{2})", second_text or "")
        second_ts = int(m2.group(1)) * 3600 + int(m2.group(2)) * 60 + int(m2.group(3)) if m2 else -1
        shot_path_1_after = shot(page, "1-auto-refresh-after")
        delta = (second_ts - first_ts) % 86400
        results["1"] = {
            "name": "Auto-refresh works",
            "pass": delta >= 5,
            "first_text": first_text,
            "second_text": second_text,
            "delta_sec": delta,
            "screenshot_before": shot_path_1_before,
            "screenshot_after": shot_path_1_after,
        }

        # =========================================================
        # 2. Footer text is honest
        # =========================================================
        footer_text = page.locator("#last-refreshed").text_content() or ""
        contains_5s = "5s" in footer_text
        contains_30s = "30s" in footer_text
        results["2"] = {
            "name": "Footer text 5s (no 30s)",
            "pass": contains_5s and not contains_30s,
            "footer_text": footer_text,
            "contains_5s": contains_5s,
            "contains_30s": contains_30s,
        }

        # =========================================================
        # 4. GET /api/heartbeat returns 3 agents
        # (do this early — independent of any UI state)
        # =========================================================
        status_code_get, hb_resp = http_get("/api/heartbeat")
        agent_ids = sorted([h.get("agent") for h in hb_resp.get("heartbeats", [])])
        expected = sorted(["thor", "forge", "argus"])
        all_have_fresh = all("fresh" in h for h in hb_resp.get("heartbeats", []))
        results["4"] = {
            "name": "GET /api/heartbeat returns 3 agents with fresh flag",
            "pass": (hb_resp.get("count") == 3) and (agent_ids == expected) and all_have_fresh,
            "count": hb_resp.get("count"),
            "agent_ids": agent_ids,
            "expected": expected,
            "all_have_fresh": all_have_fresh,
            "status_code": status_code_get,
            "ttl_sec": hb_resp.get("ttl_sec"),
        }

        # =========================================================
        # 5. Green pulse badge renders for live agent
        # (do this while the page is still active and thor is "live")
        # =========================================================
        # Force a POST heartbeat so thor is "live"
        http_post("/api/heartbeat", {"agent": "thor"})
        time.sleep(0.5)
        # Wait until at least one .agent-card contains "live"
        page.wait_for_function(
            "() => { const cards = document.querySelectorAll('.agent-card'); for (const c of cards) if (c.textContent.includes('live')) return true; return false; }",
            timeout=12000,
        )
        pulse_count = page.locator(".agent-card:has-text('Thor') .live-pulse").count()
        pulse_text = (
            page.locator(".agent-card:has-text('Thor') .live-pulse").first.text_content()
            if pulse_count >= 1
            else None
        )
        shot(page, "5-thor-live-pulse")
        results["5"] = {
            "name": "Green pulse badge renders for live agent",
            "pass": pulse_count == 1,
            "pulse_count": pulse_count,
            "pulse_text": pulse_text,
        }

        # =========================================================
        # 7. Unknown agent rejected
        # =========================================================
        status_code_400, hacker_resp = http_post("/api/heartbeat", {"agent": "hacker"})
        results["7"] = {
            "name": "Unknown agent rejected (400)",
            "pass": status_code_400 == 400,
            "status_code": status_code_400,
            "response": hacker_resp,
        }

        # =========================================================
        # 8. No regression on other panels
        # =========================================================
        # Refresh page so we get a clean render, then wait 10s for polls
        page.reload(wait_until="networkidle")
        time.sleep(10)
        panel_results = {}
        # Real error patterns we care about (not labels like "Errors: 0")
        error_patterns = [
            r"\bloading\.{0,4}\b",                      # "loading..." stuck
            r"Failed to load",
            r"TypeError:",
            r"ReferenceError:",
            r"SyntaxError:",
            r"\buncaught\b",
            r"404 Not Found",
            r"500 Internal Server Error",
        ]
        for label in PANELS:
            section = page.locator(f"section:has(h2:has-text('{label}'))").first
            try:
                body_text = section.locator(".body").first.text_content() or ""
            except Exception as e:
                panel_results[label] = {"error": str(e), "body_chars": 0}
                continue
            stuck_loading = bool(re.search(r"\bloading\.{0,4}\b", body_text, re.I))
            # An actual error = matches a real error pattern AND the body has
            # at least 30 chars (so a tiny panel saying "loading" doesn't
            # dominate). Also exclude the label "Errors\n        0" / "Errors: 0".
            normalized = re.sub(r"\s+", " ", body_text)
            has_real_error = False
            for pat in error_patterns[1:]:  # skip "loading" since handled above
                if re.search(pat, normalized, re.I):
                    has_real_error = True
                    break
            panel_results[label] = {
                "stuck_loading": stuck_loading,
                "has_real_error": has_real_error,
                "body_chars": len(body_text.strip()),
                "snippet": body_text.strip()[:160],
            }
        all_ok = all(
            pr.get("stuck_loading") is False
            and pr.get("has_real_error") is False
            and pr.get("body_chars", 0) > 0
            for pr in panel_results.values()
        )
        shot(page, "8-full-page")
        full_page_path = SCREENSHOT_DIR / "argus-mc-live-refresh-8-fullpage.png"
        page.screenshot(path=str(full_page_path), full_page=True)
        results["8"] = {
            "name": "No regression on other panels (9 panels)",
            "pass": all_ok,
            "panels": panel_results,
            "full_page_screenshot": str(full_page_path),
        }

        # =========================================================
        # Now the time-sensitive checks (3 and 6).
        #
        # Both depend on heartbeat aging out. The page auto-pings
        # /api/heartbeat every 5s which keeps thor fresh. So we must
        # CLOSE the page before the 130s wait.
        # =========================================================
        page.close()
        context.close()

        # Step A: ensure thor's heartbeat is fresh now so the 130s wait
        # starts from a known point
        http_post("/api/heartbeat", {"agent": "thor"})
        time.sleep(0.5)

        # Read agents BEFORE waiting — confirm currently live
        _, agents_before_wait = http_get("/api/data/agents")
        thor_before_wait = next(a for a in agents_before_wait["agents"] if a["id"] == "thor")
        la_before_wait = thor_before_wait["last_activity"]
        hb_age_before = thor_before_wait.get("heartbeat_age_seconds")
        hb_fresh_before = thor_before_wait.get("heartbeat_fresh")

        # Wait 130 seconds — no page open to keep pinging
        wait_start = time.time()
        time.sleep(130)
        wait_elapsed = round(time.time() - wait_start, 1)

        # Reopen page to read agents AFTER waiting
        ctx2 = browser.new_context(viewport={"width": 1400, "height": 1000})
        page2 = ctx2.new_page()

        _, agents_after_wait = http_get("/api/data/agents")
        thor_after_wait = next(a for a in agents_after_wait["agents"] if a["id"] == "thor")
        la_after_wait = thor_after_wait["last_activity"]
        hb_age_after = thor_after_wait.get("heartbeat_age_seconds")
        hb_fresh_after = thor_after_wait.get("heartbeat_fresh")

        results["6"] = {
            "name": "Heartbeat ages out (TTL=120s)",
            "pass": la_after_wait != "live",
            "before": la_before_wait,
            "after": la_after_wait,
            "elapsed_sec": wait_elapsed,
            "heartbeat_fresh_before_wait": hb_fresh_before,
            "heartbeat_fresh_after_wait": hb_fresh_after,
            "heartbeat_age_after_wait": hb_age_after,
        }

        # =========================================================
        # 3. POST /api/heartbeat flips thor to "live"  (non-live → live)
        #    Now thor is NOT live, so this is a clean transition.
        # =========================================================
        shot_before_3 = None
        # Use the page2 to grab a "before" card screenshot
        page2.goto(BASE + "/", wait_until="networkidle")
        page2.wait_for_function(
            "() => { const c = document.querySelector('.agent-card'); return c && c.textContent.length > 10; }",
            timeout=10000,
        )
        # The page2 is auto-pinging thor every 5s, but the heartbeat just
        # aged out so we have ~5s before thor goes live again. Capture before.
        time.sleep(0.5)
        shot_before_3 = shot(page2, "3-thor-card-before-agedout")

        # Read agents — confirm thor is NOT live
        _, agents_before3 = http_get("/api/data/agents")
        thor_before3 = next(a for a in agents_before3["agents"] if a["id"] == "thor")
        before_la3 = thor_before3["last_activity"]

        # POST heartbeat
        post_status, post_resp3 = http_post("/api/heartbeat", {"agent": "thor"})
        time.sleep(0.5)

        # Read agents AFTER
        _, agents_after3 = http_get("/api/data/agents")
        thor_after3 = next(a for a in agents_after3["agents"] if a["id"] == "thor")
        after_la3 = thor_after3["last_activity"]

        # Wait for the next 5s refresh so the card visibly shows "live"
        page2.wait_for_function(
            "() => { const cards = document.querySelectorAll('.agent-card'); for (const c of cards) { if (c.textContent.includes('Thor') && c.textContent.includes('live')) return true; } return false; }",
            timeout=12000,
        )
        shot_after_3 = shot(page2, "3-thor-card-after-live")
        results["3"] = {
            "name": "Heartbeat flips thor to live (non-live → live)",
            "pass": (after_la3 == "live") and (before_la3 != "live"),
            "before_last_activity": before_la3,
            "after_last_activity": after_la3,
            "post_status_code": post_status,
            "post_resp": post_resp3,
            "screenshot_before": shot_before_3,
            "screenshot_after": shot_after_3,
        }

        browser.close()

    RESULT_FILE.write_text(json.dumps(results, indent=2, default=str))
    overall = all(r.get("pass") for r in results.values() if isinstance(r, dict) and "pass" in r)
    print(json.dumps({"overall_pass": overall, "results": {k: v.get("pass") for k, v in results.items() if isinstance(v, dict)}}, indent=2))
    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    main()
