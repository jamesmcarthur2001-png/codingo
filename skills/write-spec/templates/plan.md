# Plan: <feature name>

Spec: `spec.md` · Status: DRAFT | APPROVED (<date>)

<!--
Format rules (scripts/scope_check.py parses this file):
- 2–4 slices. Each is a `## Slice <n>: <name>` header. No other headers inside a slice.
- `Files:` comes first, then one `- \`path\`` bullet per file, repo-relative, forward slashes.
  A folder ending in `/` or a glob (`services/evermore/app/entities/*.py`) is allowed.
- A changed file not listed in any slice up to the current one fails check_slice.py.
- Tests are not listed here: test files come from the File column of test-plan.md.
- Order slices by dependency: model/migration → manager/reader → API route → proxy route → frontend types/client → components/views.
-->

## Slice 1: <name, e.g. "evermore model + reader">
Files:
- `path/a.py` (new)
- `path/b.py` (edit)
Covers: REQ-1, EC-2
Pattern: P-2 (`reference/file.py`)  <!-- or: NEW, because <reason> -->
Tasks:
- <concrete step>
- <concrete step>
Verify: `<command from the service map>`

## Slice 2: <name>
Files:
- `path/c.py`
Covers: REQ-2
Pattern: P-1 (`reference/other.py`)
Tasks:
- <concrete step>
Verify: `<command>`

## Git
- Branch: <Branch from state.md> · Base: <Base from state.md>
- No commits during the build. `finish_branch.py` makes one commit `<ticket>: <spec title>`, rebases on the base, pushes with `--force-with-lease`, waits for the pipeline.
