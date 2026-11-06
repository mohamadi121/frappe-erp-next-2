# QA / Testing (sub-skill of software-development)

## Standing rule: Playwright, always
Every automated UI / E2E / browser test uses **Playwright Test** (https://github.com/microsoft/playwright, `@playwright/test`, TypeScript by default). Also use Playwright for API tests (`request` fixture), visual checks (screenshot assertions) and accessibility checks. Do not introduce Cypress, Selenium, Puppeteer or Jest-DOM-in-browser for these unless the user explicitly asks. If a project already uses another E2E tool, tell the user and propose migrating rather than silently adding to it. Unit tests keep the project's own runner (Vitest/Jest/pytest/...).

Fast path: `npm init playwright@latest`; record starting points with `npx playwright codegen <url>`; then rewrite them to the conventions below.

For driving a real browser while developing (checking a UI change, reproducing a bug), prefer **Playwright CLI** (`npm i -g @playwright/cli@latest`, https://github.com/microsoft/playwright-cli): token-efficient because it does not load big tool schemas or accessibility trees. Playwright MCP (`npx @playwright/mcp@latest`) is the alternative.

Graphify-first still applies: before writing tests, `graphify query/path` from the changed code to find callers, routes and flows that need coverage.

## Playwright conventions
1. **Locators**: `getByRole` > `getByLabel` > `getByPlaceholder` > `getByText` > `getByTestId` > CSS/XPath (last resort, max 2 levels). Lists/tables: container first, then `filter()`, then act. `nth()` only when order is a business rule, with a comment.
2. **Assertions**: web-first, auto-retrying (`await expect(locator).toBeVisible()/toHaveText()/toHaveURL()/toHaveCount()`). No manual `textContent` comparisons. Every test asserts a business outcome (order created, balance changed), not just a title/URL/class name.
3. **Waiting**: rely on auto-waiting. Never `waitForTimeout`; wait on a condition (response, locator state).
4. **Isolation**: each test independent, own browser context, own data/keys; no ordering between tests. Context isolation does not isolate the server, so also isolate accounts/data and clean up in reverse dependency order.
5. **Login reuse**: setup project writes `storageState` (`auth.setup.ts`), tests reuse it.
6. **Structure**: `e2e/tests/{smoke,regression,api}`, `pages/` (Page Objects, semantic methods), `fixtures/` (custom fixtures), `utils/`, `test-data/`, `config/`. Don't over-abstract before the core path is stable.
7. **Mock only what you don't own**: `page.route()` for third-party/flaky dependencies and for error, empty and slow-response cases. Prefer real backend for first-party flows.
8. **Config**: `baseURL`, `projects` (chromium, firefox, webkit as needed), `retries` only on CI, `trace: 'on-first-retry'`, screenshots/video on failure, reporters (`html` locally; add `junit`/`blob` in CI), `workers` + `--shard` for CI scale, `fullyParallel`.
9. **Tags**: `@smoke`, `@regression`, etc. with `--grep`; smoke on every PR, regression nightly/pre-release.
10. **Stability gate**: run a new test repeatedly (`--repeat-each=5`) before merge; fix flakiness the same day.
11. **Debugging order**: Trace Viewer (actions, snapshots, network, console) > UI mode > `--debug`. Keep traces/logs and nonzero exit codes, including first-retry failures.
12. **CI**: GitHub Actions or the project's CI; install browsers with `npx playwright install --with-deps`; upload report and traces as artifacts.
13. **Lint**: `@typescript-eslint/no-floating-promises` to catch missing `await`.

## Flaky test policy
- Never hide failures with blind retries; retries are a signal, not a fix.
- Investigate with evidence: failure rate, races, shared state, data pollution, external dependencies, resource pressure, seeds/ordering, local-vs-CI differences. Root-cause claims need a reproduction.
- Quarantine only with an owner and exit criteria; fix or delete, don't leave skipped tests forever.

## Regression selection
- Choose the smallest sufficient set from existing tests based on change risk (change coverage, business criticality, failure history, redundancy, cost, environment dependency). Never select by test name alone; make inclusions and exclusions traceable; add exploratory checks where a high risk has no mapped test; state residual risk.
- Graphify supplies the blast radius: `graphify path`/`explain` from the diff to affected flows.

## Test design discipline (from naodeng's QA skills)
- Start from requirements and risk, not from the UI. Separate facts, assumptions and open questions; if input is incomplete, deliver a bounded first pass and say what is unsupported. Never invent system behavior, data or metrics.
- Use techniques deliberately: boundary values, equivalence partitions, decision tables, state transitions, pairwise combinations, error guessing, exploratory charters.
- Rank by business impact x likelihood x detectability; don't mark everything high priority.
- Verify assertion sensitivity with a paired control: a deliberately wrong business state must make the test fail, and parallel A/B accounts must not interfere.
- Separate "generated test assets", "real browser run" and "accepted" in reports. Do not claim a test passes unless it actually ran.
- Release/regression workflows: sprint testing, release go/no-go, production verification, metrics anomaly analysis; for AI features: LLM evals, tool-call/agent behavior, prompt-injection testing.

## Sources (referenced, not vendored)
Licensed PolyForm Noncommercial (fine for personal use; do not copy into commercial/redistributed material):
- https://github.com/naodeng/awesome-qa-skills: ~330 QA agent skills (skills/en and skills/zh: testing-workflows, testing-types). Notable: `ui-test-playwright`, `api-testing`, `flaky-test-analysis`, `regression-test-selection`, `release-testing-workflow`, `discover-testing` (router), `llm-testing`, `prompt-injection-testing`. Install one: `npx skills add naodeng/awesome-qa-skills --skill <name>`. Fetch a file on demand: `gh api repos/naodeng/awesome-qa-skills/contents/<path> -q .content | base64 -d`.
- https://github.com/naodeng/awesome-qa-prompt: 256 QA prompts (requirements, test design, API, performance, security, release, AI testing), Chinese and English.
- https://github.com/naodeng/30-day-qa-playwright-learning-plan: 30-day Playwright curriculum; Day 29 has the team-standards template (naming, locators, POM, data, tags, CI strategy, failure triage, PR review checklist).
- Official: https://playwright.dev/docs/best-practices
