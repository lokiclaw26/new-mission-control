---
name: ai-coding-cli-delegation
description: "Delegate coding tasks to autonomous AI coding-agent CLIs (Claude Code, OpenAI Codex, OpenCode) from Hermes. Covers one-shot run mode for bounded tasks, interactive PTY sessions for multi-turn work, background process monitoring, parallel worktrees, PR review delegation, and CLI-specific gotchas (PTY requirement, exit commands, sandbox flags, model selection). Use when the user says 'use Claude Code', 'delegate to Codex', 'run OpenCode', or asks Hermes to spawn an external coding agent to build, refactor, or review code."
version: 2.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Coding-Agent, Claude-Code, Codex, OpenCode, Anthropic, OpenAI, Open-Source, Code-Review, Refactoring, PR-Delegation, PTY, Background-Process, Parallel-Worktrees, AI-Agent-CLI, Autonomous-Coding]
    related_skills: [github-workflows, hermes-agent]
    category: autonomous-ai-agents
---

# AI Coding CLI Delegation

Class-level playbook for delegating coding work to autonomous AI agent CLIs from Hermes. Three CLIs are supported today — **Claude Code** (Anthropic), **Codex** (OpenAI), and **OpenCode** (open-source, provider-agnostic) — and they share most of the same orchestration patterns: one-shot run mode, interactive PTY session, background process monitor, parallel worktrees, PR review.

## Decision tree — which CLI?

| Need | Use | Why |
|------|-----|-----|
| Default for one-shot coding tasks | **Claude Code** (`claude -p`) | Most mature, broadest model family, structured JSON output |
| OpenAI-only model preferences or sandboxed build | **Codex** (`codex exec`) | Native OpenAI models, `--full-auto` sandboxed workspace |
| Provider-agnostic / local / OSS / specific openrouter model | **OpenCode** (`opencode run`) | Use any provider — Anthropic, OpenAI, local — through one CLI |
| User explicitly named the CLI | Use that one | Don't second-guess the user |

If the user didn't name one, default to **Claude Code** unless the task description suggests a constraint (cost ceiling, OSS requirement, specific provider).

**Do not use this skill for configuring Hermes itself** — that's `hermes-agent`. This skill is for *delegating work out* to other coding CLIs.

---

## 1. The shared orchestration patterns

All three CLIs follow the same two-mode structure. Choose based on whether you need iteration.

### Mode A: One-shot (non-interactive, exits when done)

Best for bounded, well-specified tasks: "add a feature", "fix this bug", "refactor this module", "review this PR diff".

```bash
# Claude Code
terminal(command="claude -p 'Add retry logic to API calls in src/' --allowedTools 'Read,Edit' --max-turns 10", workdir="/path/to/project", timeout=120)

# Codex (always pty=true; always inside a git repo)
terminal(command="codex exec 'Build a snake game in Python'", workdir="/path/to/project", pty=true)

# OpenCode (no pty needed for `run`)
terminal(command="opencode run 'Refactor the auth module'", workdir="/path/to/project")
```

**When to use:** clear spec, single deliverable, no need for follow-up, CI/automation.
**Pros:** clean exit, easy to capture result, deterministic.
**Cons:** no iteration, no follow-up corrections.

### Mode B: Interactive PTY / background session (multi-turn)

Best for iterative work, exploration, long tasks where the CLI may ask questions, or tasks where you want to monitor progress in real time.

```bash
# Start in background (always pty=true for the TUI; tmux optional for Claude Code)
terminal(command="<cli>", workdir="/path/to/project", background=true, pty=true)
# Returns session_id

# Send a prompt
process(action="submit", session_id="<id>", data="Implement OAuth refresh flow and add tests")

# Monitor
process(action="poll", session_id="<id>")
process(action="log",   session_id="<id>")

# Send follow-up
process(action="submit", session_id="<id>", data="Now add error handling for token expiry")

# Exit (NEVER use `/exit` for OpenCode — opens an agent selector instead)
process(action="write", session_id="<id>", data="\x03")   # Ctrl+C
# Or just kill
process(action="kill", session_id="<id>")
```

**When to use:** multi-step, the CLI may ask clarifying questions, you want to review progress.
**Pros:** iterative, observable, can redirect.
**Cons:** needs `pty=true`, harder to capture structured output, sessions can drift.

### The PTY rule

All three CLIs use a terminal UI. **Always pass `pty=true` to the `terminal` tool for interactive sessions.** Without a PTY the CLI hangs or misbehaves. The one exception is Claude Code's `claude -p` (print mode) and OpenCode's `opencode run` — those are non-interactive and don't need a PTY.

### Monitoring long tasks

```bash
process(action="list")              # see all background processes
process(action="poll", session_id)  # quick check — prints new output
process(action="log",   session_id) # full log with pagination
```

Be patient with long-running code work. Don't `kill` a session just because it's been silent for 30 seconds — the agent may be running tests, building, or thinking.

---

## 2. Parallel execution pattern (worktrees)

For batch issue fixing or multi-PR review, run one CLI per worktree in parallel:

```bash
# Create worktrees
terminal(command="git worktree add -b fix/issue-78 /tmp/issue-78 main")
terminal(command="git worktree add -b fix/issue-99 /tmp/issue-99 main")

# Launch one CLI in each (background + pty)
terminal(command="codex --yolo exec 'Fix issue #78: <desc>. Commit when done.'", workdir="/tmp/issue-78", background=true, pty=true)
terminal(command="codex --yolo exec 'Fix issue #99: <desc>. Commit when done.'", workdir="/tmp/issue-99", background=true, pty=true)

# Monitor
process(action="list")

# When done, push + PR each
terminal(command="cd /tmp/issue-78 && git push -u origin fix/issue-78")
terminal(command="gh pr create --repo user/repo --head fix/issue-78 --title 'fix: ...' --body '...'")
```

Use this when issues are independent. If they share code or risk conflict, run them sequentially.

---

## 3. PR review delegation

The cheapest use of these CLIs is "review this PR" — bounded, low-risk, no commits. Two patterns:

### In-place (current branch is the PR)

```bash
# OpenCode has a built-in shortcut
terminal(command="opencode pr 42", workdir="/path/to/repo", pty=true)

# Or generic
terminal(command="opencode run 'Review PR #42 against main. List bugs, security risks, and test gaps.'", workdir="/path/to/repo")
```

### Isolated (clone to temp dir, safer)

```bash
REVIEW=$(mktemp -d)
git clone https://github.com/user/repo.git $REVIEW
cd $REVIEW && gh pr checkout 42
<cli> review --base origin/main      # or `run`/`-p` with a review prompt
```

The isolated pattern is preferred for security-sensitive reviews or when you don't want the CLI to touch your working tree.

---

## 4. CLI-specific gotchas (don't get burned)

| Gotcha | CLI | Symptom | Fix |
|--------|-----|---------|-----|
| Workspace trust dialog appears on first run | Claude Code | Hangs at "Yes, I trust this folder" | Send `Enter` to accept (default is correct) |
| Permissions bypass warning dialog | Claude Code | Appears with `--dangerously-skip-permissions` | Navigate Down then Enter (default is WRONG) |
| `/exit` opens agent selector | OpenCode | Stays in TUI, doesn't exit | Use `Ctrl+C` (`\x03`) or `process(action="kill")` |
| `Enter` must be pressed twice | OpenCode TUI | First press finalizes text, second sends | Press Enter twice |
| Codex refuses to run outside a git repo | Codex | Immediate error | `cd $(mktemp -d) && git init && <cmd>` for scratch |
| Codex sandbox fails in containerized context | Codex | `setting up uid map: Permission denied` | Use `--sandbox danger-full-access` and rely on process boundaries for safety |
| `opencode` PATH mismatch | OpenCode | Wrong binary/model config between terminal and Hermes | `which -a opencode`, then pin explicit `$HOME/.opencode/bin/opencode run` |
| Print mode without `-p` | Claude Code | Drops into interactive REPL | Always `claude -p "task"` for automation |

---

## 5. CLI comparison

| Aspect | Claude Code | Codex | OpenCode |
|--------|------------|-------|----------|
| Vendor | Anthropic | OpenAI | Open-source (anomalyco) |
| Install | `npm i -g @anthropic-ai/claude-code` | `npm i -g @openai/codex` | `npm i -g opencode-ai@latest` |
| One-shot | `claude -p "..."` | `codex exec "..."` | `opencode run "..."` |
| Interactive | `claude` (REPL) | `codex` (TUI) | `opencode` (TUI) |
| Needs PTY (interactive) | yes | yes | yes |
| Needs PTY (one-shot) | no | yes | no |
| Needs git repo | no | **yes** | no (recommended) |
| Model flexibility | Anthropic only | OpenAI only | Any provider via config/env |
| JSON output | `--output-format json` | `--json` | `--format json` |
| Session resume | `--resume <id>` / `--continue` | session storage | `opencode -c` / `-s <id>` |
| Built-in PR review | via sub-agent | `codex review` | `opencode pr <num>` |
| Sandboxed default | permission prompts | `workspace-write` | permission prompts |
| Bypass sandbox | `--dangerously-skip-permissions` | `--yolo` / `--sandbox danger-full-access` | `--auto-approve` |
| Background-friendly | yes | yes (with pty) | yes (with pty for TUI) |

---

## 6. Auth setup quick reference

```bash
# Claude Code
claude auth login                  # browser OAuth
claude auth login --console        # API key billing
claude auth login --sso            # Enterprise SSO
claude auth status                 # check
claude doctor                      # health check

# Codex
codex                              # first-run will prompt for login
export OPENAI_API_KEY=...          # OR set API key
# For Hermes: hermes auth add openai-codex   # OAuth via ~/.hermes/auth.json

# OpenCode
opencode auth login                # interactive provider setup
opencode auth list                 # verify at least one provider configured
export OPENROUTER_API_KEY=...      # OR set provider env vars
```

For machine-readable JSON status (Claude Code): `claude auth status` returns JSON; add `--text` for human format.

---

## 7. Cross-cutting pitfalls

1. **Always `pty=true` for interactive sessions.** Without it, the CLI hangs. Print mode (`-p`, `exec`, `run`) is the exception.
2. **Don't `/exit` OpenCode.** Use `Ctrl+C` (`\x03`) or `process(action="kill")`.
3. **Codex needs a git repo.** For scratch work: `cd $(mktemp -d) && git init && codex exec "..."`.
4. **Set `--max-turns` (Claude) or be patient (Codex/OpenCode).** Claude Code's print mode takes `--max-turns N`; otherwise the agent loops until it decides it's done. For Codex/OpenCode monitor with `process(action="poll")`.
5. **Use `--max-budget-usd` (Claude) for cost control.** Print-mode only.
6. **Be patient with long sessions.** Don't kill a silent session too early — the agent may be running tests.
7. **PATH and binary pinning matter.** If `which -a opencode` shows multiple binaries, pin the explicit path.
8. **Don't use one working directory for parallel sessions.** Use worktrees or `/tmp/<task>-<n>/`.
9. **Report concrete outcomes back to the user.** "Files changed: src/auth.py, tests/test_auth.py. Tests: 24/24 pass. Remaining: manual smoke test of OAuth callback."

## 8. `delegate_task` gotchas (Hermes sub-agent spawning, not external CLI)

`delegate_task` is the Hermes-native way to spawn an isolated sub-agent for a task. It is NOT the same as `claude -p` or `codex exec`. Specific gotchas observed in real NofiTech workflows:

10. **`delegate_task` sub-agents can hit `HTTP 429 Token Plan usage limit reached` mid-task (2026-06-16, MC-AGENT-LOG-FIX-1).** A sub-agent that consumes 1.4M input tokens (e.g. a long task with extensive file reads) can be killed by the parent platform's rate limiter before it finishes. The error surfaces as `status: completed, exit_reason: max_iterations, error: API call failed after 3 retries: HTTP 429: Token Plan usage limit reached`. **Fix:** for long tasks, design the brief so the sub-agent does the heavy reading in its own context (not the parent's). The brief should already include the relevant file paths and key snippets so the sub-agent doesn't re-read the world. If a sub-agent hits 429, treat it as partial completion — read its log file, identify what's missing, spawn a second sub-agent with the smaller scope (NOT do the work yourself — see `thor-orchestrate-only`).

11. **`delegate_task` is sequential, not truly parallel (even when called in one batch).** The `tasks: [...]` batch mode in `delegate_task` may run sub-agents concurrently at the platform level, but each sub-agent shares the same workspace, and the parent's tool calls are still serialized for the response. If two sub-agents edit the same file, last-write-wins. **Fix:** if the tasks are truly independent (different files, different scopes), batch them. If they share state (e.g. one builds, the other verifies), run them sequentially — first sub-agent finishes, parent audits, then second sub-agent runs. The "split-into-second-subagent" recovery pattern in `operator-driven-staged-delivery` uses this sequentially: Forge first (build + log), then Argus (verify + log), with the parent doing the audit between.

12. **The 600s ceiling is per-sub-agent, not per-batch.** Each sub-agent in a batch gets its own 600s budget. They do NOT share time. The 600s budget is also INCLUSIVE of the sub-agent's tool calls and the platform's overhead — a sub-agent that does 50 small reads may run out of budget before doing the actual work. **Fix:** in the sub-agent's brief, be explicit about what is most important to do first ("if you run out of time, leave the state.json update for a second sub-agent — the log file and code edits are highest priority").

13. **The sub-agent's exit reason is not a verdict on the work.** A sub-agent that exits with `status: completed, exit_reason: completed` may have done 100% of the work OR 50% OR 0% — the platform only knows whether the conversation loop ended. Always verify the sub-agent's claims with disk reads (`ls`, `stat`, `grep`, `cat`) before accepting them. See `references/subagent-conflicting-reports.md` for the audit pattern.

---

## See also

- `references/claude-code.md` — full Claude Code reference (CLI flags, PTY dialog handling, output formats, subcommands, MCP, session management)
- `references/codex.md` — full Codex reference (`exec`, `--full-auto`, worktree patterns, batch PR review, gateway sandbox caveat)
- `references/opencode.md` — full OpenCode reference (`run`, TUI keybindings, session resume, parallel work, PR review, pitfalls)
- `github-workflows` skill — for the PR creation, CI monitoring, and merge steps that follow delegation
- `hermes-agent` skill — for configuring Hermes itself (NOT delegated coding work)
