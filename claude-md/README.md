# CLAUDE.md drafts for midnight-api

Drafts from PROPOSAL.md §4.2. The midnight-api repo isn't on this machine, so they live here with the same
relative paths they get in the repo. Folder paths are placeholders: check them against the real layout.

| File here | Copy to (in midnight-api) | What it holds |
|---|---|---|
| `CLAUDE.md` | `CLAUDE.md` (repo root) | Repo map, how to check work, scope, questions, git, the few rules shared by every service |
| `services/evermore/CLAUDE.md` | `services/evermore/CLAUDE.md` | CRUD + real-data validation, transactions |
| `services/evermore/tests/CLAUDE.md` | `services/evermore/tests/CLAUDE.md` | The inventory test model (wins over pytest-conventions) |
| `services/twilight/CLAUDE.md` | `services/twilight/CLAUDE.md` | Reverse-proxy rules and what to test |
| `libs/midnight_models/CLAUDE.md` | `libs/midnight_models/CLAUDE.md` | Models only |
| `frontend/CLAUDE.md` | `frontend/CLAUDE.md` | Frontend rules a script can't check |

Claude Code loads a folder's CLAUDE.md whenever it reads a file in that folder.
If you can't commit them to the team repo yet, save each one as `CLAUDE.local.md` in the same folder (git-ignored),
or as `.claude/rules/<name>.md` with a `paths:` glob, if your Claude Code version supports rules (unverified).

Optional extra rule for `services/evermore/tests/CLAUDE.md` (not in the original notes):
"Don't assert on the count or order of all rows; filter to the rows the test fetched."
