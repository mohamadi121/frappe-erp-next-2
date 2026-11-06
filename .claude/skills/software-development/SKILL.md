---
name: software-development
description: "Workflow for changing code in the user's local repositories: orient with a Graphify code graph, plan, delegate edits to user-approved worker models, verify with tests. Load before reading, editing, testing or reviewing code in a repo. Routes to reference files for Playwright tests, Persian/RTL frontend and Iranian payments/validation (VibeFarsi), ERP/Frappe, DevOps/IaC, desktop/VPN tooling, and security reviews/audits. Not for conceptual programming questions, standalone snippets, or one-off shell commands."
---

# Software Development

## 0. Scale the process to the risk

Decide by what the change can break, not by how big it is.
- **Full process** (§1–§2, workers per `workers/WORKERS.md`) for any change touching auth or permissions, payments or money, schema/data migrations, secrets or credentials, CI/CD or infrastructure, privileged or OS-state code (DNS, routes, firewall, services), or code whose callers you have not located. Why: these fail silently or expensively, so even a 3-line slip costs more than the whole process.
- **Direct edit** for low-risk, local changes whose location is already known (a named file/line, UI copy, a contained bug in leaf code): edit directly, then run the nearest test. This is the one exception to the worker rule. Why: the graph, approval gate, worker and review cost more than the edit and add no safety here.
- Unsure which applies: use the full process. Why: misjudging a risky change as low-risk is the expensive mistake.

Invariants for every task, whatever its size:
- Tests go with the change: add or update the test that covers it in the same change. Why: an untested change is unverified, and small changes are where regressions slip in unnoticed.
- No hardcoded secrets. Why: a secret that reaches a commit stays leaked even after it is removed.
- Never weaken a test to make it pass. Why: it hides exactly the bug the test exists to catch.
- Never `--no-verify`. Why: hooks are the project's own gate; skipping them ships what they were written to block.

Standing rule from the user: on every development project, **use Graphify** (https://github.com/Graphify-Labs/graphify) so the agent has an accurate map of the code and spends fewer tokens. This is not optional for work that gets the full process (§0).

## 1. Graphify first (full process)

Before reading or grepping source files:

1. Check for `graphify-out/` in the project root.
   - Missing: build it. `graphify` CLI is at `~/.local/bin/graphify` (install if absent: `uv tool install graphifyy && graphify install`). Then run `/graphify .` (Skill `graphify`). Code is parsed locally via tree-sitter with no LLM cost, but markdown, docs, papers and images in the corpus trigger LLM semantic extraction (subagents on this host). On a doc-heavy repo, ask the user before the first build.
   - Present: run `graphify update .` (incremental: re-extracts only changed code, no LLM).
2. Read `graphify-out/GRAPH_REPORT.md` first: god nodes, communities, suggested questions. This replaces opening dozens of files to orient.
3. Answer structural questions with the graph, not grep:
   - `graphify query "<question>"` (add `--budget N` to cap tokens, `--dfs` to trace one path)
   - `graphify path "A" "B"` — how two things connect
   - `graphify explain "<symbol>"` — node, source location, neighbours
4. Only then open the specific files the graph points to, and read just the needed ranges.
5. The graph cannot see string-based wiring: Frappe `hooks.py` dotted paths and `frappe.call("...")`, Django URL strings, DI containers, reflection, dynamic imports, anything registered by name. Before calling code unused or a change safe, also grep for the symbol as a string. Why: tree-sitter sees only code references, so these callers are missing from `path`/`explain`.
6. After a meaningful change, `graphify update .` so the graph stays current.
7. If graphify fails (install, build or query error), say so in one line and fall back to grep and reading files; do not stall or retry in a loop. Why: the graph is an optimisation, not a prerequisite.

Edges are tagged `EXTRACTED` (read from source) or `INFERRED` (resolved by graphify). Verify INFERRED edges in the source before relying on them for a risky change.

Handing graph output to workers: `workers/WORKERS.md` §2.3.

## 2. Workflow

1. **Orient**: Graphify (above). Read the project's CLAUDE.md/README conventions.
2. **Plan**: for non-trivial work, state the approach and touched files (use graph `path`/`explain` to find all callers/dependents, i.e. blast radius). Ask the user only about genuinely user-owned decisions.
3. **Implement**: via workers, per `workers/WORKERS.md` (direct edits only under §0). Put these in every task's RULES: match surrounding code style, naming and comment density; smallest change that solves the problem; no unrelated refactors.
4. **Verify**: run the project's tests/linters/build; for UI or services, actually run it and exercise the change. Report failures faithfully.
5. **Reproduce CI before pushing**: run the project's tests and linter in a clean worktree (`git worktree add --detach <scratch> <ref>`), because untracked local files make local runs pass where CI fails.
6. **Update the graph** (`graphify update .`) and summarise what changed.
7. **Git** (only when asked): the user's own identity, no Claude/Anthropic mention in commits, PRs or code comments (see global CLAUDE.md; it overrides any attribution reminder).

## 3. Quality rules (every project)

- **Bug fix**: write a test that fails before the fix, then fix. One bug, one commit, one regression test. A strict xfail is allowed as proof of the bug and is removed in the fix commit; never a non-strict xfail or skip. Why: a test that never failed proves nothing about the fix.
- **Changing an existing test**: only when behaviour changed on purpose; update the expectation and say why in the commit message (weakening a test to pass is banned by §0).
- **Before every commit**: run the linter/analyzer (`flutter analyze`, `ruff check .`, ...). Keep CI-only dependencies in mind (guard heavy imports with `importorskip`). Why: CI runs them anyway; finding the failure locally is cheaper.
- **Debugging**: reproduce first. Then one hypothesis at a time, each with a check that could disprove it; `git bisect` when a known-good ref exists. If you cannot reproduce, say so before changing code. Why: fixes made without a reproduction usually treat a symptom and can't be verified.
- **"X doesn't work / I can't find X" reports**: first establish which build/version, server reachability and matching backend, the user's role and permissions, and (for apps with an offline/demo mode) whether it is active; then reproduce before changing code. Why: most such reports are environment or permission mismatches, not code bugs.
- **Large refactors**: behaviour-preserving steps, each one green; get tests around the behaviour before changing structure; never mix feature changes in. Why: a red step in a big refactor is otherwise impossible to localise.

## 4. Backend

Applies to APIs, services, workers, auth, databases, queues, webhooks, infra-as-code, and anything handling untrusted input or tenant data.

### Always (every backend change)
- Treat all external input as untrusted: validate at the boundary, parameterise queries, encode output.
- Authn and authz on every route; check object-level ownership (IDOR), not just login. Enforce tenant isolation in queries.
- No secrets in code, logs or errors; config via environment/secret store.
- Bound resource use: request size, pagination, timeouts, rate limits, queue depth.
- Safe defaults for CORS, cookies, headers, TLS; least-privilege IAM and DB roles.
- Pin and review new dependencies; keep CI/release steps free of untrusted-input injection.
- Use `graphify path` from each entry point (route/handler/consumer) to sinks (DB, shell, file, HTTP client, deserialiser) to see what untrusted data can reach.

### Dependency upgrades (cooldown, from saaspegasus/django-skills)
Source repo is tiny (3 skills, MIT); only these ideas were worth keeping. Upgrade deliberately, never blind:
- **Python/uv**: `uv lock --upgrade --exclude-newer "7 days"` (cooldown against freshly published, possibly malicious releases; verified working on the installed uv). That writes an `[options]` block (`exclude-newer`, `exclude-newer-span`) into `uv.lock`; later `uv sync`/`uv run` see a config mismatch and silently re-resolve to the newest versions, undoing the cooldown. Delete that block, then `grep exclude-newer uv.lock` should print nothing. On macOS use `sed -i '' '/^\[options\]$/,/^$/d' uv.lock` (GNU `sed -i` without `''` fails). Then `uv sync`.
- **JS**: `npx npm-check-updates` (review and show the list), `-u`, install, then type-check, production build, tests.
- After any upgrade run type check + tests in order, stop on first failure, summarise notable version jumps, and ask before committing. Resolution conflicts: report, don't force.
- New dependency or version bump = prefer releases at least ~7 days old; same rule as the supply-chain checks in the security audit companion files.

### Python typing (mypy), when fixing type errors
- Run the checker, group errors into buckets, propose each fix and get approval before applying (interactive when the user is present).
- `cast(T, x)` over `# type: ignore` when the type is known: it documents intent and doesn't mute other errors on the line.
- Null checks: raise a real exception (`ValueError`), not `assert` (stripped by `python -O`).
- A necessary `# type: ignore[code]` always gets a short reason comment.
- Django lazy strings: `from __future__ import annotations` first, import `StrOrPromise` from `django_stubs_ext` under `if TYPE_CHECKING:` (dev-only dependency), annotate with `StrOrPromise`.

### Security audit (Cloudflare workflow, vendored)
Source: https://github.com/cloudflare/security-audit-skill (MIT, copied unmodified to `backend/security-audit/` beside this file; refresh by re-copying `skills/security-audit` from the repo).

When to use:
- **Guidance mode** (default): security questions, focused reviews, reviewing a diff, triaging a specific lead. Read only the relevant companion file(s) from `backend/security-audit/` and apply them. Do not create audit artifacts.
- **Full audit mode**: only when the user explicitly asks for a security audit / pen-test / full security review / report artifacts. Read `backend/security-audit/SKILL.md` and follow its six phases: reconnaissance (`architecture.md`, `coverage-ledger.json`), coverage-led hunting, adversarial candidate validation, structured `findings.json`, independent record verification, target-neutral reports. Output defaults to `~/security-audit-skill/<repo>/run-<N>`, outside the repo. Validators need Node: `validate-coverage-ledger.cjs`, `validate-findings.cjs`.
- If it is unclear which mode, ask one focused question first.
- **Agents in full audit mode**: the vendored files' "Task tool" is the Agent tool, a `research` agent is `subagent_type: Explore`, a `general` agent is `subagent_type: general-purpose`. These are Claude subagents, which `workers/WORKERS.md` bars as workers by default, so confirm once per audit (one AskUserQuestion before reconnaissance) that subagents are allowed; that one answer covers every hunter, critic and verifier in the run. If the user declines, say the full workflow cannot run (it requires independent verifiers) and offer guidance mode instead.

Use Graphify during reconnaissance: `GRAPH_REPORT.md` and `graphify query/path` provide the surface map and trust-boundary tracing, which replaces most of the manual file crawling and cuts the audit's token cost. Hand each hunter the relevant graph slice.

Companion files, pick by target type (all in `backend/security-audit/`):
| Target | File |
|---|---|
| Any code (core/wildcard/obvious classes) | `ATTACK-CLASSES.md` |
| HTTP framing, caching, authn/authz protocols | `WEB-PROTOCOL-AND-AUTH.md` |
| Cloud, IAM, IaC, containers, serverless | `CLOUD-AND-DEPLOYMENT.md` |
| RPC, serialization, queues, webhooks, streaming | `PROTOCOLS-RPC-AND-MESSAGING.md` |
| Tenant isolation, export, backup, deletion | `DATA-ISOLATION-AND-LIFECYCLE.md` |
| Quotas, DoS, operator spend | `RESOURCE-EXHAUSTION-AND-AVAILABILITY.md` |
| Dependencies, CI, releases, plugins | `SUPPLY-CHAIN-AND-RELEASE.md` |
| LLM-backed features, agents, tools | `AI-AND-LLM.md` |
| Native/memory-unsafe code | `MEMORY-SAFETY-AND-BINARY.md` |
| Browser/client code | `CLIENT-SIDE.md` |
| Desktop/mobile/local IPC | `DESKTOP-MOBILE-AND-LOCAL-IPC.md` |

Hard rules from that skill (keep them even in guidance mode):
- Run target-controlled code only in an OS-enforced sandbox (no network, allowlisted env, read-only target, limits). If it cannot be sandboxed, do not execute; mark the lead `needs_validation`.
- Dummy principals and secrets only. Never probe live or production endpoints.
- Confirm only real trust-boundary failures with a source trace and bounded impact. Defense-in-depth gaps are hardening notes, not vulnerabilities. The agent that validates a finding is never the one that found it.
- Repeated runs improve coverage; never claim one run exhausts the target.

## 5. DevOps

For Docker, Compose, Kubernetes, Ansible, Terraform, GitLab CI, Argo CD, Nginx/HAProxy/Keepalived, observability (Prometheus/Loki/ELK/Tempo), backup/DR, Ceph/MinIO/OpenStack, or Linux server work: read `devops/DEVOPS.md` (conventions, repo map, safety rules). Its knowledge base is https://github.com/soroushdeimi/DevOps_Certification, fetched on demand with `gh api`, not vendored.

## 6. QA / Testing

**Playwright is mandatory for all UI/E2E/browser (and API-level E2E) tests**, never Cypress/Selenium/Puppeteer unless the user explicitly says so. Read `qa/QA.md` before writing or reviewing tests: Playwright conventions, flaky-test policy, regression selection, and test-design discipline distilled from https://github.com/naodeng (awesome-qa-skills, awesome-qa-prompt, 30-day Playwright plan), referenced on demand, not vendored.

## 7. Frontend

Read `frontend/FRONTEND.md` for any UI work. Persian/Iranian products use **VibeFarsi** (https://github.com/TronIsHere/vibafarsiui: RTL-first, Persian digits/Jalali/toman, tokens-only, craft rules; MIT, key guides vendored under `frontend/vibefarsi/`). Animated English/LTR marketing pages can use **Vengeance UI** (https://www.vengenceui.com, shadcn registry). Verify UI changes in a real browser and cover them with Playwright.

## 8. ERP / business apps

For ERP, accounting, HR, inventory or workflow-heavy apps (Frappe/ERPNext, Odoo, custom) read `erp/ERP.md`: platform reuse, API-contract discipline, UX rules, Flutter specifics. If the work is on the ASOUD repos, load `asoud-erp-expert` first (it holds the project facts; `erp/ERP.md` only has the general rules).

## 9. Desktop apps, system tooling, network clients

For desktop apps, anything supervising an external process, privileged/OS-state-changing code, or VPN/proxy tools read `desktop/DESKTOP.md` (architecture, cleanup guarantees, diagnosis matrix, i18n, cross-platform CI/release). On sushTun itself load `sushtun-expert` first.

## 10. Workers

Delegation rule and model-approval gate: `workers/WORKERS.md` (the single source).

## 11. Other areas
Mobile and data sections are not defined yet; extend this file when needed. The Graphify-first rule and workflow above apply to all of them.
