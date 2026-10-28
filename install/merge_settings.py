#!/usr/bin/env python3
"""
Adds the midnight-workflow hooks to ~/.claude/settings.json, or removes them, without touching anything else.

Usage: python3 merge_settings.py add <settings.json> <hooks.json>
       python3 merge_settings.py remove <settings.json>
`add` backs the settings file up first, drops this workflow's earlier hook entries and adds the current ones,
so running it again never duplicates them. Entries are recognised by their script path.

:author: midnight-workflow
:date: 28/10/2026
"""
# ----- Imports ----- #

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

# ----- Consts ----- #

WORKFLOW_SCRIPT_MARKER = "/.claude/midnight-workflow/scripts/hooks/"
HOOKS_KEY = "hooks"
BACKUP_TIME_FORMAT = "%Y%m%d-%H%M%S"

# ----- Classes ----- #


class SettingsFileError(Exception):
    """
    Raised when settings.json isn't a JSON object, so it can't be merged safely.
    """
    pass

# ----- Functions ----- #


def is_workflow_hook(hook: object) -> bool:
    return isinstance(hook, dict) and WORKFLOW_SCRIPT_MARKER in str(hook.get("command", ""))


def without_workflow_hooks(hooks: dict[str, object]) -> dict[str, object]:
    """
    Remove this workflow's hook entries, keeping every other hook and event as it was.

    :param hooks: The `hooks` object of settings.json.
    :return: The hooks without this workflow's entries; matcher groups and events left empty are dropped.
    """
    cleaned: dict[str, object] = {}
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            cleaned[event] = groups
            continue

        kept_groups: list[object] = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                kept_groups.append(group)
                continue

            kept_hooks = [
                hook
                for hook in group["hooks"]
                if not is_workflow_hook(hook)
            ]
            if len(kept_hooks) > 0:
                kept_groups.append({**group, "hooks": kept_hooks})

        if len(kept_groups) > 0:
            cleaned[event] = kept_groups

    return cleaned


def add_workflow_hooks(settings: dict[str, object], workflow_hooks: dict[str, list[object]]) -> dict[str, object]:
    """
    Put this workflow's hooks into the settings, replacing an earlier install of them.

    :param settings: The parsed settings.json.
    :param workflow_hooks: The hooks snippet (event to matcher groups).
    :return: New settings with every other key kept.
    """
    existing_hooks = settings.get(HOOKS_KEY)
    hooks = without_workflow_hooks(existing_hooks) if isinstance(existing_hooks, dict) else {}
    for event, groups in workflow_hooks.items():
        event_groups = hooks.get(event)
        merged_groups = list(event_groups) if isinstance(event_groups, list) else []
        merged_groups.extend(groups)
        hooks[event] = merged_groups

    return {**settings, HOOKS_KEY: hooks}


def remove_workflow_hooks(settings: dict[str, object]) -> dict[str, object]:
    existing_hooks = settings.get(HOOKS_KEY)
    if not isinstance(existing_hooks, dict):
        return settings
    hooks = without_workflow_hooks(existing_hooks)
    if len(hooks) == 0:
        return {
            key: value
            for key, value in settings.items()
            if key != HOOKS_KEY
        }
    return {**settings, HOOKS_KEY: hooks}


def read_settings(path: Path) -> dict[str, object]:
    if not path.is_file() or path.read_text(encoding="utf-8").strip() == "":
        return {}
    settings = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(settings, dict):
        raise SettingsFileError(
            f"{path} is not a JSON object; fix it by hand first.",
        )
    return settings


def write_settings(path: Path, settings: dict[str, object]):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        backup_path = path.with_name(
            f"{path.name}.bak-{time.strftime(BACKUP_TIME_FORMAT)}",
        )
        shutil.copy2(path, backup_path)
        print(f"Backed up {path} to {backup_path}")
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(settings, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add or remove the midnight-workflow hooks in settings.json.",
    )
    parser.add_argument("action", choices=["add", "remove"])
    parser.add_argument("settings", type=Path)
    parser.add_argument(
        "hooks",
        type=Path,
        nargs="?",
    )
    arguments = parser.parse_args()
    try:
        settings = read_settings(arguments.settings)
    except SettingsFileError as settings_error:
        print(settings_error, file=sys.stderr)
        return 1
    if arguments.action == "add":
        if arguments.hooks is None:
            parser.error("add needs the hooks.json snippet")
        workflow_hooks = json.loads(arguments.hooks.read_text(encoding="utf-8"))
        write_settings(
            arguments.settings,
            add_workflow_hooks(settings, workflow_hooks),
        )
        return 0
    if not arguments.settings.is_file():
        return 0
    write_settings(
        arguments.settings,
        remove_workflow_hooks(settings),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
