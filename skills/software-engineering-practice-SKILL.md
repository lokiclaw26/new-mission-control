---
name: software-engineering-practice
description: "Use when applying a software engineering methodology or practice to a code task — TDD (write the test first, red-green-refactor), systematic debugging (root cause before fix), simplify-code (parallel 3-agent cleanup of recent changes), spike (throwaway prototype before build), or pre-commit code review (security + quality gates + auto-fix). All five are class-level practice skills adapted from obra/superpowers + gsd. NOT for running tests on a build (use project test commands), NOT for actual debugger attach (use python-debugpy / node-inspect-debugger), NOT for project planning (use plan)."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [tdd, debugging, code-review, simplification, spike, prototype, engineering-practice, methodology, superpowers]
    related_skills: [plan, subagent-driven-development, python-debugpy, node-inspect-debugger]
---

# Software Engineering Practice — methodology before code

You need to apply an engineering discipline to a coding task. Five class-level practice skills cover the methodology lifecycle — from validating an idea, to writing tests first, to debugging, to cleanup, to pre-commit review. Each has an Iron Law: violation of the letter is violation of the spirit.

## Pick the right practice

| Phase | Skill | Use when |
|---|---|---|
| **Validate before building** | **spike** | Throwaway prototype to feel out an idea, compare approaches, surface unknowns that research can't answer. Disposable by design. |
| **Write code with tests** | **test-driven-development** | Any new feature, bug fix, refactor, or behavior change. Iron Law: write the test first, watch it fail, write minimal code to pass. |
| **Debug a failure** | **systematic-debugging** | Any technical issue (test failure, prod bug, unexpected behavior, performance). Iron Law: NO FIXES WITHOUT ROOT CAUSE FIRST. |
| **Clean up recent changes** | **simplify-code** | After writing code, run three focused reviewers (reuse, quality, efficiency) in parallel and apply the fixes worth applying. |
| **Verify before commit** | **requesting-code-review** | Before `git commit` / `git push` / "ship" / "done" — security scan + quality gates + independent reviewer + auto-fix. |

## Lifecycle order

```
spike  →  test-driven-development  →  systematic-debugging  →  simplify-code  →  requesting-code-review
  │                                       ↑
  │                                       └── invoked when tests fail
  └─→ (if idea is infeasible, stop here and report)

(review approval may route back to TDD if reviewer requests changes)
```

A typical task flow:

1. **Idea → spike.** Validate feasibility, compare 2-3 approaches, surface unknowns. Throw away the spike, keep the verdict.
2. **Build → test-driven-development.** Write the test first. Watch it fail. Write minimal code. Watch it pass. Refactor.
3. **Failure → systematic-debugging.** If a test or run fails, root-cause before fixing. Phase 1 (reproduce) → Phase 2 (hypothesize) → Phase 3 (instrument) → Phase 4 (fix).
4. **Cleanup → simplify-code.** Three parallel reviewers: reuse, quality, efficiency. Aggregate findings, apply fixes worth applying.
5. **Ship → requesting-code-review.** Pre-commit pipeline: static scan, baseline-aware quality gates, independent reviewer, auto-fix loop.

## Common pitfalls across all five

1. **Skipping a phase because "this is obvious".** Every phase has a non-trivial failure mode that skipping invites.
2. **Treating the Iron Laws as flexible.** "I just wrote the production code, I'll write the test after" = "I don't know if the test verifies the right thing."
3. **Fixing symptoms.** If you can't articulate the root cause in one sentence, you're not in Phase 4 of debugging — go back.
4. **"Let me just commit and see."** No. Run requesting-code-review. Fresh context finds what you miss.

## When NOT to use any of these

- For *running* tests on a build, use the project's test command — not a methodology skill.
- For *attaching a debugger* to a running process (Python, Node), use `python-debugpy` / `node-inspect-debugger`.
- For *planning* a multi-stage project, use `plan`.
- For *reviewing someone else's PR on GitHub*, use `github-code-review`.
- For *subagent-driven development orchestration*, use `subagent-driven-development` (composes these).

## Full guides

Each subsection's full body lives under `references/`:

- [`references/test-driven-development.md`](references/test-driven-development.md) — Iron Law, RED-GREEN-REFACTOR cycle, anti-rationalization patterns
- [`references/systematic-debugging.md`](references/systematic-debugging.md) — 4-phase root cause process, anti-pattern table
- [`references/simplify-code.md`](references/simplify-code.md) — 3-agent parallel review, aggregation, focus modifiers
- [`references/spike.md`](references/spike.md) — decompose → research → build → verdict loop, MANIFEST format
- [`references/requesting-code-review.md`](references/requesting-code-review.md) — diff retrieval, static scans, quality gates, auto-fix

## Related skills

- `plan` — multi-stage project planning (lifecycle container for these practices)
- `python-debugpy`, `node-inspect-debugger` — runtime debugger attachment (NOT methodology)
- `subagent-driven-development` — orchestration that composes these practices per-stage
- `github-code-review` — review OTHER people's PRs (this umbrella reviews YOUR changes)
- `shell-token-redaction-workaround` — practical shell-side pattern that complements these practices