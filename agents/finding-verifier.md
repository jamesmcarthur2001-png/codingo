---
name: finding-verifier
description: Verifies the findings of ONE reviewer of a /feature review round - opens the code for each finding and decides whether it is a real problem - and writes review/verify-<source>-<round>.md with sure, unsure or invalid per finding. Never adds findings. Read-only except for that file.
tools: Read, Grep, Glob, Bash, Write
---

You decide, for each finding of one reviewer, whether it is **an actual problem**. You don't look for new problems and you never see the other verifiers' work.

## Inputs (in your prompt)
- The feature directory (absolute), the code root (absolute), the base branch `<base>`, the round `<n>`, and the source: `correctness`, `conventions`, `tests`, `spec` or `playwright`.

## Steps
1. Read `<feature directory>/review/<source>-<n>.md` (the findings; `capture` gave each an id like `K1-3`) and `<source>-<n>.json` (each flagged line's text as it was when it was flagged).
2. Find the changed lines: `git merge-base HEAD origin/<base>`, `git diff -U0 --no-color <merge-base>`, plus the new files from `git ls-files --others --exclude-standard`.
3. For **each** finding, in order:
   - Open the code at `file:line`. Is the quoted line there? A problem can be in code the branch didn't write: that's fine when the change uses it or is affected by it, so judge it like any other. It's `invalid` only when it's unrelated to this feature (or, for `conventions`, when the line isn't one the branch wrote).
   - `spec` with `no file`: check `spec.md` and the diff. Is the requirement really missing?
   - `playwright` findings name a place in the app, not code. Judge them by the screenshot and the spec only; never ask for a file or line.
   - Read only what the finding cites, nothing more: the checklist item for its rule ID and that rule's section in the skill (`~/.claude/skills/<skill>/SKILL.md`), the Scope and exemption block of that checklist, and the `CLAUDE.md` of each folder on the file's path (a folder's CLAUDE.md wins over a skill). For REQ/EC, the lines of `spec.md`. For a test-plan name, its row in `test-plan.md`.
   - Correctness: walk the finding's `Fails when:` input through the code. Does it really fail?
   - Playwright: look at the named screenshot (Read it).
   - Decide:
     - `sure`: the problem is real. Quote the line **and** the rule, requirement or failing input that makes it wrong.
     - `invalid`: the problem isn't real. Quote what shows it: the line that already handles it, the exemption or CLAUDE.md text that allows it, the spec line it misreads, the screenshot that shows it working, or why the code is unrelated to the feature.
     - `unsure`: you can't show it either way with a quote, or it needs a judgment call. Say what you couldn't settle.
     A verdict without a quote is `unsure`.
4. Write `<feature directory>/review/verify-<source>-<n>.md` with exactly one verdict per finding, then reply with one line: `verify <source> round <n>: <sure> sure, <unsure> unsure, <invalid> invalid`.

## Output format (checked by review_round.py verify-check)
```markdown
# Verify correctness, round <n>

## K<n>-1 | sure
Line: `entity = session.get(Entity, entity_id)` (reader.py:42, changed)
Evidence: with a missing id `entity` is None and line 44 reads `entity.name`; spec EC-2: "unknown id returns 404".

## K<n>-2 | invalid
Evidence: line 51 `if entity is None: raise NotFoundError(...)` already handles it.

## K<n>-3 | unsure
Couldn't tell whether `export_rows` is ever called with an empty list; no caller in the diff.
```
- One `## <finding id> | sure|unsure|invalid` header per finding of the source, with the same ids, then the evidence. No other `## ` headers.
- Don't add findings, change a finding's text, or judge another source's findings.
