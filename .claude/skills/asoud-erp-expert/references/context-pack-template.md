# Context pack: put this block (15 to 30 lines) at the top of every worker task

Weak models fail from guessing, not from lack of length. Give the facts the code does not reveal, nothing more.

```
CONTEXT PACK
Goal in one sentence: <what the user sees working afterwards>
Words: <Persian UI terms in this task -> code names; see references/glossary.md>
Files to read first: <3-6 paths with one line each on why>
Endpoint(s): <module.method, roles needed, REAL example response copied from the backend or a live call>
Similar code/test to imitate: <path:line>
Do not touch: <files/areas out of scope>
Already known (do not rediscover): <e.g. 417 is terminal, admin has no Employee row>
Done when: <exact commands that must pass + the one behaviour to verify by hand>
```
Rules for the manager: copy real response JSON (mask secrets), name the exact failing screen from the screenshot, and keep one task to at most three bugs.

## Live test tasks: always add the screenshot rule
Every live test saves one screenshot per distinct screen and state with `.team/bin/ui EMU shot NN_page-state`, copies them to `<workspace>/ui-audit/<date>-v<version>/` and writes an `INDEX-<tester>.md` (file | page and how to reach it | UX notes). The folder is the baseline for later UI/UX work and before/after comparisons.
