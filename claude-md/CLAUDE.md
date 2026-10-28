# midnight-api
evermore = CRUD service, validates real data · twilight = reverse proxy · midnight_models = shared models only.

## Scope
New code follows the conventions. Existing lines change only when the task needs them changed.
Don't rename, reformat, retype, reorder or "fix" existing code for conventions, even in a file you're editing.

## Asking me questions
Before asking about a requirement, restate it in one sentence in my words, then ask.

## Checking
Say something works, passes, or is how the architecture behaves only after checking it, and show the output.
If you can't check it, say so and raise it as an open problem.

## Git
- One branch per ticket: BTRC-<n>-short-description. Never create a second branch for the same BTRC-<n>.
- At the end of a merge: pull the base branch (master, the branch I named, or the one we're based on today).
- End of branch: commit, pull --rebase on the base, push the feature branch with --force-with-lease, make sure
  the pipeline passes, stop this branch's containers, remove the worktree.

## Python
- New functions never start with get_: entity_by_id, not get_entity_by_id.
- Full years: 2026, not 26.
- Strings of 5+ words are constants. Except where reading them in place matters: error messages, raise, settings.
- New routers use prefix=, not tags=.
- No # noqa, # type: ignore, # pylint: disable. Fix the code instead.
