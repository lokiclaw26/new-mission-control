#!/usr/bin/env python3
"""
MC-KANBAN-DONE-PILL-1 migration (one-shot, 2026-06-19).

For every task file where `kanban_status: done` but `status` is anything
other than `done`, set `status: done` in the frontmatter (or the Format B
table row). This is the data backfill for the cascade fix in
`_patch_format_a` and `_patch_format_b` — they only apply to NEW PATCH
operations; existing done cards still have `status: in_progress` from
the pre-cascade era and need a one-time fix.

Idempotent: tasks already at `status: done` are skipped.
Safe: writes to disk via the same parser helpers that ship the parser
PATCH. No network, no API calls, no server restart needed.

Usage:
    python3 scripts/migrate-cascade-done-status.py [--dry-run] [--root <path>]

Output: a list of (task_id, path, before, after) tuples. In dry-run mode,
nothing is written.
"""
import argparse
import re
import sys
from pathlib import Path

# Reuse the parser's helpers so the format detection is identical
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))
from kanban_parser import (  # noqa: E402
    _iter_task_files,
    _split_frontmatter,
    parse_frontmatter,
    parse_markdown_table,
    detect_format,
    _normalize_status,
    _TABLE_ROW_KV_RE,
    _TABLE_HEADER_RE,
    _TABLE_SEP_RE,
)


def _backfill_format_a(path: Path) -> tuple[bool, str]:
    """If the card lands in the Done column (per the parser's logic) and
    `status` is not already `done`, set `status: done`. Returns
    (changed, before_status).

    A card is "in the done column" when EITHER:
      - the file has an explicit `kanban_status: done`, OR
      - the file has NO kanban_status field AND `status` normalizes to
        `done` (e.g. `complete` -> `done` per the parser's _normalize_status
        table at kanban_parser.py:70).

    This handles the case where old-format task files used
    `status: complete` to mean "done" — the parser already routes them
    to the Done column, but the raw status text on the card still reads
    "complete" and NOFI can't tell them apart from a Done card at a glance.

    Two-pass: first read the whole header to decide whether the cascade
    applies, then a second pass rewrites the status line in place. This
    handles files where the `status:` key appears BEFORE `kanban_status:`
    in the frontmatter.
    """
    txt = path.read_text(encoding="utf-8")
    header, body, _ = _split_frontmatter(txt)
    if not header:
        return False, ""
    kanban_status_value = ""
    status_idx = None
    status_before = ""
    for i, line in enumerate(header):
        m = re.match(r'^(\s*kanban_status\s*:\s*)(.*?)(\s*(?:#.*)?)$', line)
        if m:
            kanban_status_value = m.group(2).strip()
        m2 = re.match(r'^(\s*status\s*:\s*)(.*?)(\s*(?:#.*)?)$', line)
        if m2:
            status_idx = i
            status_before = m2.group(2).strip()
    # Use the same normalization the parser uses (kanban_parser._normalize_status)
    # for the case where kanban_status is absent.
    if kanban_status_value:
        col_status = kanban_status_value.lower()
    else:
        col_status = _normalize_status(status_before)
    if col_status != "done":
        return False, ""
    if status_idx is None:
        # No status line — inject one at the top of the header
        new_header = ["status: done"] + list(header)
        out = "---\n" + "\n".join(new_header) + "\n---\n" + "\n".join(body)
        if not out.endswith("\n"):
            out += "\n"
        path.write_text(out, encoding="utf-8")
        return True, ""
    if status_before.lower() == "done":
        return False, status_before
    # Rewrite the status line in place — NOFI's mental model is
    # "Done column = status=done". Anything else (in_progress, complete,
    # failed, blocked, open, assigned, etc.) reads as "not done" on a card
    # that sits in the Done column. So we cascade in every case where the
    # file is in the done column. Safe because Done is terminal.
    new_header = []
    for i, line in enumerate(header):
        if i == status_idx:
            m2 = re.match(r'^(\s*status\s*:\s*)(.*?)(\s*(?:#.*)?)$', line)
            new_header.append(f"{m2.group(1)}done{m2.group(3)}")
        else:
            new_header.append(line)
    out = "---\n" + "\n".join(new_header) + "\n---\n" + "\n".join(body)
    if not out.endswith("\n"):
        out += "\n"
    path.write_text(out, encoding="utf-8")
    return True, status_before


def _backfill_format_b(path: Path) -> tuple[bool, str]:
    """Same as _backfill_format_a but for the table format. A card is
    considered "in the done column" if either the kanban_status row says
    done OR the kanban_status row is missing and the status value
    normalizes to done (per the parser's _normalize_status table).
    """
    txt = path.read_text(encoding="utf-8")
    lines = txt.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if _TABLE_HEADER_RE.match(line):
            header_idx = i
            break
    if header_idx is None:
        return False, ""
    data_start = header_idx + 1
    if data_start < len(lines) and _TABLE_SEP_RE.match(lines[data_start]):
        data_start += 1
    status_row_idx = None
    status_value = None
    kanban_status_value = ""
    for j in range(data_start, len(lines)):
        ln = lines[j]
        if not ln.lstrip().startswith("|"):
            break
        m = _TABLE_ROW_KV_RE.match(ln)
        if not m:
            break
        raw_key = m.group("key").strip()
        if raw_key.startswith("**") and raw_key.endswith("**") and len(raw_key) >= 4:
            key = raw_key[2:-2].strip().lower()
        else:
            key = raw_key.strip().lower()
        if key == "status":
            status_row_idx = j
            status_value = m.group("val").strip()
        elif key == "kanban_status":
            kanban_status_value = m.group("val").strip()
    if status_row_idx is None:
        return False, ""
    if kanban_status_value:
        col_status = kanban_status_value.lower()
    else:
        col_status = _normalize_status(status_value or "")
    if col_status != "done":
        return False, ""
    if status_value is not None and status_value.lower() == "done":
        return False, ""
    # Re-build the status row, preserving the key rendering
    ln = lines[status_row_idx]
    m = _TABLE_ROW_KV_RE.match(ln)
    raw_key = m.group("key").strip()
    lines[status_row_idx] = f"| {raw_key} | done |"
    out = "\n".join(lines)
    if not out.endswith("\n"):
        out += "\n"
    path.write_text(out, encoding="utf-8")
    return True, status_value or ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/home/nofidofi/NofiTech-Ind",
                    help="NofiTech-Ind repo root")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would change but do not write")
    args = ap.parse_args()

    root = Path(args.root)
    files = _iter_task_files(root)
    fixed = []
    skipped = 0
    for tf in files:
        try:
            txt = tf.read_text(encoding="utf-8")
        except Exception:
            continue
        fmt = detect_format(txt)
        if args.dry_run:
            # In dry-run, parse without writing
            if fmt == "A":
                meta, _ = parse_frontmatter(txt)
                ks = (meta.get("kanban_status") or "").strip().lower()
                st = (meta.get("status") or "").strip().lower()
                if ks == "done" and st != "done":
                    fixed.append((meta.get("task_id", tf.stem), tf, st, "done"))
            elif fmt == "B":
                tbl, _ = parse_markdown_table(txt)
                ks = (tbl.get("kanban_status") or "").strip().lower()
                st = (tbl.get("status") or "").strip().lower()
                if ks == "done" and st != "done":
                    fixed.append((tbl.get("id", tf.stem), tf, st, "done"))
            continue
        if fmt == "A":
            changed, before = _backfill_format_a(tf)
        elif fmt == "B":
            changed, before = _backfill_format_b(tf)
        else:
            changed, before = False, ""
        if changed:
            # get task_id for logging
            txt2 = tf.read_text(encoding="utf-8")
            if fmt == "A":
                meta, _ = parse_frontmatter(txt2)
                tid = meta.get("task_id", tf.stem)
            else:
                tbl, _ = parse_markdown_table(txt2)
                tid = tbl.get("id", tf.stem)
            fixed.append((tid, tf, before, "done"))
        else:
            skipped += 1

    print(f"Scanned {len(files)} task files. Would fix / fixed: {len(fixed)}. Skipped (no change needed): {skipped}.")
    for tid, path, before, after in fixed:
        print(f"  {tid}  ({path.name})  status: {before!r} -> {after!r}")
    if args.dry_run:
        print("(dry run — no files modified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
