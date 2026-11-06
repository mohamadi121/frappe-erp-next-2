STYLE (from the user; follow exactly)
- Code: plain, minimal, no extra refactors, no new dependencies. Comments: one short plain line for a non-obvious why.
- Commits: Conventional Commit with scope, short, describe only the change, user's git identity. Never mention any AI tool, assistant or model anywhere (code, comments, docs, strings, commits). No trailers.
- Tests: real edge and failure cases, no skip/only/xfail, no loosened asserts; break a key test, see red, restore, name it in the report. Test the real file, not a copy. Expected numbers come from running the library.
- Accuracy: units on every number, constants from the library or a named source; never overclaim; no invented data.
- Never guess: unsure => .worker/QUESTION.md and stop that item. Report NOT VERIFIED for anything unverified. "Doubts: none" is not accepted.
- Replies short. Do not edit files you do not own.
- Never commit demo tests that assert a wrong value fails, and never delete existing tests to get green: break the code temporarily, see red, restore.
