---
description: "Audit a library's docs against its code (flag every false or outdated claim with the correction), then map out the skills the library needs. Writes reports only; changes no code or docs."
argument-hint: "<path to the library root> [--docs <path>] [--skills-dir <path>]"
disable-model-invocation: true
---

# Map a library

Request: `$ARGUMENTS`

Audit one library and produce two reports:
1. **`doc-audit.md`**: every claim in the docs checked against the code. Each wrong, outdated, or misleading claim is flagged with the evidence and the corrected text.
2. **`skill-map.md`**: the skills this library needs, each with its scope, its trigger description, and the source files it should be built from.

This is a standalone command. It isn't part of `/midnight-workflow:feature` and doesn't touch `docs/features/`.

## Arguments
- First positional argument: the library root (required). Stop and ask if it's missing or doesn't exist.
- `--docs <path>`: an extra docs location outside the library root (e.g. a separate docs repo or wiki export). Can be repeated.
- `--skills-dir <path>`: existing skills to check for overlap. Defaults to `<library>/.claude/skills/` plus this plugin's `skills/`.

## Rules
- **Read-only.** Don't change the library's code or docs. The only files you write are under `<library>/docs/library-audit/`.
- **The code is the source of truth.** A doc claim is correct only if you read the code that proves it. Cite `file:line` for every verdict.
- **Never guess.** If a claim can't be settled from the code (e.g. it depends on an external service or runtime config), mark it `unverifiable` and say what you looked for.
- **Don't run anything with side effects.** Static reading is the default. You may run the library's own test suite or a self-contained doc example only when it needs no network, database, credentials, or writes outside a temp dir. Record which ones you ran.
- If `docs/library-audit/` already exists, overwrite the reports, but read the old `skill-map.md` first and keep any hand-written notes under "Decisions" unless the code now contradicts them.

---

## Phase 1: Inventory
Write `<library>/docs/library-audit/inventory.md`. It's the shared input for both agents, so keep it factual and compact (under ~300 lines).

1. **Identity:** name, language(s), version, and package manifest (`pyproject.toml`, `package.json`, …). Note the install name and the import name.
2. **Public surface:** what users of the library actually call. Use `__all__`, `__init__.py` re-exports, `exports` in `package.json`, `index.ts`, CLI entry points, and registered plugins or hooks. List each public module, class, function, CLI command, config key, and env var with its `file:line`. Mark anything private-but-documented.
3. **Docs:** every doc source. That means `README*`, `docs/`, `*.md` / `*.rst` / `*.mdx` anywhere in the library, `CHANGELOG`, `examples/`, notebooks, docstrings of the public surface, and any `--docs` path. Record the line count of each.
4. **Tests:** where the tests are and how to run them (from the manifest, Makefile, or CI config).
5. **Batches:** split the doc sources into audit batches of roughly 1,500 doc lines each, keeping each file whole and grouping related files. Docstrings form their own batch, grouped by module. Use at most 8 batches; if there would be more, batch by importance (README, getting started, API reference first) and list the rest as "not audited" in the final report.

## Phase 2: Audit the docs (parallel)
Run one `midnight-workflow:doc-auditor` agent per batch, **all in parallel**. Give each one:
- the library root,
- the path to `inventory.md`,
- its batch number and file list,
- its output path: `<library>/docs/library-audit/audit/batch-<n>.md`.

Wait for all of them. If an agent failed or its file is missing, re-run that batch once. If it fails again, list the batch as "not audited".

## Phase 3: Merge the audit
Write `<library>/docs/library-audit/doc-audit.md` from the batch files:
- Renumber findings globally (`DA-1`, `DA-2`, …) and sort by severity, then by file.
- Merge duplicates. When the same wrong fact appears in several places, make one finding and list every location.
- Fill in the summary counts and the coverage section.

```markdown
# Doc audit: <library> (<version>, <date>)

## Summary
- Claims checked: <n> · correct: <n> · wrong: <n> · outdated: <n> · misleading: <n> · unverifiable: <n>
- Public API with no docs at all: <n> (see "Undocumented")
- Not audited: <files, or "none">

## Findings
| ID | Severity | Doc location | Claim (as written) | What the code does | Evidence | Correction |
|----|----------|--------------|--------------------|--------------------|----------|------------|
| DA-1 | wrong | `README.md:42` | "`connect(timeout=30)`" | Default is 10 s; param is `timeout_s` | `src/lib/client.py:88` | "`connect(timeout_s=10)`" |

## Undocumented
| Public symbol | Where | Why it matters |
|---------------|-------|----------------|

## Coverage
| Doc source | Claims | Issues | Notes |
|------------|--------|--------|-------|

## Ran
- <tests or examples executed, and their result>, or "nothing (static only)"
```

Severity, from worst to mildest:
- **wrong**: following the doc breaks the user's code or gives the wrong result (wrong name, signature, default, return, exception, or behavior).
- **outdated**: it was true once (renamed, removed, or deprecated; the CHANGELOG or git log shows it) and isn't now.
- **misleading**: technically true, but incomplete in a way that leads users wrong (a missing required step, an unmentioned side effect, a missing error case).
- **unverifiable**: the code can't settle it. Say what you looked for.

## Phase 4: Map the skills
Run the `midnight-workflow:skill-mapper` agent with: the library root, `inventory.md`, `doc-audit.md`, the existing skills directories (from `--skills-dir` or the defaults), and the output path `<library>/docs/library-audit/skill-map.md`. Wait for it.

## Phase 5: Report
Reply to the user with:
1. The audit counts, and the top 5 findings (`wrong` first) with their corrections.
2. The proposed skills: one line each (name: what it covers), in the order the map recommends building them.
3. Anything not audited, and the open questions from the skill map.
4. The paths of the two reports.

Don't offer to edit the docs or create the skills in this run. The user decides from the reports.
