---
name: soroush-style
description: How Soroush wants code, commits, PRs, tests, comments, reports and agent work done, so nothing is redone. Load before writing code or briefing any worker/agent for his projects (neuroSush, studio, papers, ERP, sushTun).
---

# Soroush's working style

Source: his instructions in sessions, `~/.claude/CLAUDE.md` and memory (up to 2026-11-03). Written from what he asked for and corrected, not guessed. If he changes his mind, edit this file.

## Communication
- He writes Persian. Reply in Persian with English technical terms, short, tables when comparing. No long preambles, no recap of what he said.
- He wants direct judgement: say plainly if an idea is bad, give one recommendation instead of a survey.
- Report failures plainly (what failed, output tail). Never say "done" for something not verified. Never claim more than the evidence.
- Decisions: ask an Opus agent, keep it one small question, then follow it. Do not wake or ask him at night for things you can decide.

## Git, commits, PRs (hard rules)
- Always his own git identity (his configured `user.name`/`user.email`). Never override the author.
- Never mention Claude, Anthropic, Codex, Gemini, Qwen or any AI tool/model anywhere: commits (body too), PR titles/bodies, tags, code comments, docs, site text, image metadata. No Co-Authored-By, no "Generated with".
- Conventional Commits with a scope: `feat(neurons): ...`, `fix(studio): ...`. The message describes the change only: no review chatter ("per review", "as requested").
- Squash merges keep the PR title/body: check them for the above.
- Commit/push only when he asks; he has asked for "PR + merge reviewed work, delete merged branches". Before any push: commit, then `bash ~/.claude/scripts/ci-parity.sh origin/main` (it fails on uncommitted changes; run with nohup, it takes minutes). Merge only when `gh pr checks N` shows at least 9 checks, none pending or failing; verify with `gh pr view N --json state`.
- Never touch files you do not own in a parallel package; nobody edits CHANGELOG, root README, root pyproject, ci.yml except the manager.

## Code
- Plain, readable, minimal. No speculative abstraction, no refactors outside the task, no new dependencies without need.
- neuroSush rules: pure math functions + thin behaviors; explicit `Order`; fail early with the offending value in the message; all randomness from the seeded generator; reproducible bit for bit; strict mypy, ruff lint + format.
- Every claim in docs/site must be backed by a test or a regenerable script. Numbers come from running the code, never typed by hand.
- Comments: one short plain line for a non-obvious why. No essays, no restating code, no robotic tone.

## Tests
- Real tests: edge and failure cases, not only the happy path. No skip/xfail/only, no loosened asserts to get green.
- Prove key tests can fail: break the feature, see red, restore, and name those tests in the report.
- Test the real file/object, not a copy of it. Golden numbers come from the Python library, never invented.

## Science and honesty (his top priority)
- Simulations and demos as accurate and real as possible: correct equations, units, constants, concentrations; JS math mirrors the library and is tested against it.
- Never overclaim. For the TEM work: theta is imposed; periodicity is not hexagonal; 8x8 maps are not resolvable; no "grid cells emerged"; never "better than the paper". Presentable results live only in `papers/RESULTS_AND_EXPLANATIONS.md` with their caveats; site/PR/supervisor text must come from there.
- Reference repos are read-only. Never unpickle untrusted data. Never store passwords.
- Teaching content: short, accurate, brain-science background, the equation and where its constants come from (real ratios), one classic machine-learning analogy and where it breaks. Not long.
- Site/UX: clear categories and a start-here path so a newcomer is never confused; labels with units; customizable controls; checked at 390 and 1440 px, light and dark; look at screenshots, do not trust the code.

## Toolkit-first principle

Before doing any task manually that is likely to repeat:
1. Check `~/.claude/toolkit/README.md` first — it's the index of all reusable tools.
2. `~/.claude/scripts/` is symlinks only; canonical location is `toolkit/`.
3. If a tool doesn't exist and the task will recur: build it, place in `toolkit/<category>/`, add a symlink in `scripts/`, update `toolkit/README.md`.

**Toolkit layout:**
- `toolkit/git/` — pre-push gates, CI helpers
- `toolkit/workers/` — spawn, watch, gate workers
- Project-specific scripts stay in their skill dir (`skills/<skill>/scripts/`); they're listed in `toolkit/README.md` for discoverability.

Never burn tokens doing the same thing twice when a 20-line script fixes it forever.

## Working with agents
- The manager (Claude) is the critical brain: decides, sets criteria, judges risk. Workers do the grunt work: code, screenshots, test runs, long reads. Different model reviews the author (Codex audits Gemini).
- Workers run visibly in tmux in bypass mode; scope and limits are in the prompt; never touch his own tmux windows.
- Workers must not guess: if unsure they write `.worker/QUESTION.md` and stop. Never "Doubts: none". Look up in `papers/refs/INDEX.md` first.
- Trust the diff, not the report: `bash ~/.claude/scripts/worker-gate.sh <worktree>` and break one named test by hand before accepting. Review prompts are numbered with exact text and lines.
- Briefs are short and exact: task, owned files, acceptance commands, report format. Details: `~/.claude/skills/qwen-worker`.

## Machine quirks (macOS)
- `sed -i ''`, zsh (no word-splitting, a glob with no match aborts), no `timeout`, no `ls --time-style`. Long jobs: `nohup ... &` plus `caffeinate -dimsu -w <pid>`; the lid must stay open. Never run `pmset -g thermlog`. Waiting: Monitor with an until-loop, not long sleeps.
