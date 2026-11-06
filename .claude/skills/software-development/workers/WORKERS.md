# Workers (sub-skill of software-development)

Standing rules from the user:
1. **Always delegate the coding to workers** (token management; the only exception is a low-risk direct edit under `../SKILL.md` §0): the main agent is the *manager* (understands, plans, writes exact task prompts, reviews, verifies) and workers write the code. Reading, running tests/greps/linters to verify, and merging reviewed work are the manager's job; editing source files is the worker's.
2. **Never choose a worker model on your own. Ask the user, every time, which models may be used.** Approval is not inferred from earlier sessions, from this file, from other skills' lists of "kinds in use", or from what happens to be installed.

Related skills (load them for the mechanics): `qwen-worker` (spawning/pane control, `qworker`), `qwen-task-loop` (exact old/new edit blocks, `task-status`, dry-run, byte-compare). Project-specific team setups (e.g. `asoud-erp-expert`'s `team` helper) add to these, they do not replace this gate.

## 1. Model approval gate (before the first spawn of a session, and whenever a different model is wanted)
1. Detect what is actually available on this machine (read-only probes): `command -v claude-qwen claude-gemini codex lingling opencode tmux task-status`, plus Claude subagents via the Agent tool. Candidates come from this probe only; mention a model that is installed but untested as "untested".
2. Use `AskUserQuestion` with `multiSelect: true`, one option per detected candidate, each with a one-line honest trade-off (speed, strictness, known weaknesses, cost, whether it runs in a visible tmux pane). Include "no workers this time" as a choice. Ask which models are allowed and, if relevant, which one for which kind of task (exact edits vs. open-ended logic vs. UI review).
3. Spawn only what the user selected. If the needed one is missing, unreachable or refused (e.g. account/quota error) do **not** swap in another model: report it and ask again.
4. The approval covers the current session/task set only. When a worker dies or hits a limit and a handoff to a different model is needed, ask again. Save a standing approval to memory only if the user explicitly says it is permanent.
5. Never use Claude Sonnet/Opus as a worker unless the user selects it in this question (the user has previously said they do not want that by default).
6. Probe a model with a trivial request (e.g. "Reply OK") before a big spawn, as a read-only availability check, not as a way to pick one.

## 2. Manager workflow (summary)
1. Orient with Graphify; decide the verify command(s).
2. Prototype or specify the change precisely (for weak models: exact old/new blocks per `qwen-task-loop`). Give each worker its own git worktree/branch; never share a folder; never use the user's main checkout.
3. Write a task file: TASK / CONTEXT / SPEC / RULES / HOW TO WORK / VERIFY / REPORT FORMAT. Put in Graphify output (`explain`/`path` results, exact file paths and line numbers) so the worker does not rediscover the code (this is where the token savings come from). At most ~3 bugs per task, one commit and one regression test each; never leave an old instruction next to its replacement.
4. Worker rules to include every time: no secrets in prompts (pass credentials only through a temp file and delete it); tests must be real (edge/failure cases, no skip, no non-strict xfail, no loosened asserts; a strict xfail that proves the bug before the fix is allowed and is removed in the fix commit; prove a key test can fail); short human comments; commit messages describe only the change; workers never push and never touch history; no AI/tool names anywhere.
5. Run workers visibly in the manager's tmux window when the model supports it (the user wants to watch). Permission mode is per the `qwen-worker` skill (bypass with a guard hook and `.worker/deny.txt`); never build something that presses approval keys.
6. Wait on git/report files, not by polling the screen. Handoff, never restart: if a worker dies, start the (user-approved) next model in the same worktree with "do not redo finished work; read git log/status/diff first".
7. **Review everything yourself**: read the whole report and all its files, `git log base..HEAD`, `git diff --stat`, then the production diff (not just tests); look for removed assertions/conditions, silent fallbacks around permissions, and anything touching auth/secrets. Run the linter and the FULL test suite yourself. A worker's `STATUS: PASS` means nothing until you did. Turn every `DOUBTS` line into a decision or a follow-up task.
8. Merge reviewed work into an integration branch, never force-push, undo with `git revert -m 1`. Close workers when accepted. Don't delete worktrees without the user's agreement.
9. Git rules from the user's CLAUDE.md apply to everything workers produce: the user's identity, no Claude/Anthropic mention.

## 3. Token management tips
- Manager context stays small: read diffs and short reports, not whole files; ask workers for a fixed short REPORT FORMAT.
- Keep tasks small (one module/concern); weak models degrade after ~40-50k tokens of context: `/clear` and resend a focused prompt.
- Pipeline: investigate task N+1 while a worker applies task N.
- Expect small-model workers to be slower than coding directly; the point is the user's token budget and visibility, not speed.

## 4. Environment notes
- The worker tooling and any team helper scripts were built on the user's Linux box (paths like `~/...`). On this Mac check what exists first (`claude-qwen` and `codex` were not on PATH when this was written; `claude-gemini`, `lingling`, `task-status` and `tmux` were). If tooling is missing, tell the user and ask how to proceed rather than falling back to coding yourself or to an unapproved model.
- If the user says "no workers" for a task, comply and code directly.
