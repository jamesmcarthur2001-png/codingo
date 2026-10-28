import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_DIRECTORY = Path(__file__).resolve().parents[2]
HOOKS_SNIPPET = REPO_DIRECTORY / "settings" / "hooks.json"
INSTALLED_SCRIPTS_PREFIX = "$HOME/.claude/midnight-workflow/scripts/"
IS_POSIX = sys.platform != "win32" and shutil.which("bash") is not None
OTHER_HOOK = {"type": "command", "command": "echo mine"}


def load_merge_settings():
    spec = importlib.util.spec_from_file_location("merge_settings", REPO_DIRECTORY / "install" / "merge_settings.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


merge_settings = load_merge_settings()


def hook_commands(hooks: dict[str, object]) -> list[str]:
    return [
        str(hook["command"])
        for groups in hooks.values()
        for group in groups
        for hook in group["hooks"]
    ]


def test_hooks_snippet_uses_python3_and_existing_scripts():
    commands = hook_commands(json.loads(HOOKS_SNIPPET.read_text(encoding="utf-8")))

    assert len(commands) == 4
    for command in commands:
        assert command.startswith('python3 "$HOME/.claude/midnight-workflow/scripts/hooks/')
        script_path = command.split('"')[1].removeprefix(INSTALLED_SCRIPTS_PREFIX)
        assert (REPO_DIRECTORY / "scripts" / script_path).is_file(), script_path


def test_hooks_snippet_guard_branch_timeout_is_below_its_fetch_budget():
    snippet = json.loads(HOOKS_SNIPPET.read_text(encoding="utf-8"))

    bash_hook = snippet["PreToolUse"][1]["hooks"][0]

    assert "guard_branch.py" in bash_hook["command"]
    assert bash_hook["timeout"] == 45


def test_add_workflow_hooks_keeps_other_settings_and_never_duplicates():
    snippet = json.loads(HOOKS_SNIPPET.read_text(encoding="utf-8"))
    settings = {"model": "local", "hooks": {"Stop": [{"hooks": [OTHER_HOOK]}]}}

    once = merge_settings.add_workflow_hooks(settings, snippet)
    twice = merge_settings.add_workflow_hooks(once, snippet)

    assert twice["model"] == "local"
    assert hook_commands(twice["hooks"]).count("echo mine") == 1
    assert sorted(hook_commands(twice["hooks"])) == sorted(hook_commands(once["hooks"]))
    assert len(hook_commands(twice["hooks"])) == 5


def test_remove_workflow_hooks_leaves_only_the_user_hooks():
    snippet = json.loads(HOOKS_SNIPPET.read_text(encoding="utf-8"))
    installed = merge_settings.add_workflow_hooks({"hooks": {"Stop": [{"hooks": [OTHER_HOOK]}]}}, snippet)

    removed = merge_settings.remove_workflow_hooks(installed)

    assert removed == {"hooks": {"Stop": [{"hooks": [OTHER_HOOK]}]}}


def test_remove_workflow_hooks_drops_an_emptied_hooks_key():
    snippet = json.loads(HOOKS_SNIPPET.read_text(encoding="utf-8"))
    installed = merge_settings.add_workflow_hooks({"theme": "dark"}, snippet)

    removed = merge_settings.remove_workflow_hooks(installed)

    assert removed == {"theme": "dark"}


def run_script(script_name: str, home: Path) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "HOME": str(home)}
    return subprocess.run(
        ["bash", str(REPO_DIRECTORY / script_name)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


@pytest.mark.skipif(not IS_POSIX, reason="install.sh targets Ubuntu")
def test_install_twice_then_uninstall_restores_the_user_files(tmp_path: Path):
    claude_directory = tmp_path / ".claude"
    (claude_directory / "skills" / "python-conventions").mkdir(parents=True)
    user_skill = claude_directory / "skills" / "python-conventions" / "SKILL.md"
    user_skill.write_text("my own skill\n", encoding="utf-8")
    (claude_directory / "settings.json").write_text(json.dumps({"model": "local", "hooks": {"Stop": [{"hooks": [OTHER_HOOK]}]}}), encoding="utf-8")

    first = run_script("install.sh", tmp_path)
    second = run_script("install.sh", tmp_path)

    settings = json.loads((claude_directory / "settings.json").read_text(encoding="utf-8"))
    installed_script = claude_directory / "midnight-workflow" / "scripts" / "hooks" / "next_step.py"
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert (claude_directory / "commands" / "feature.md").is_file()
    assert (claude_directory / "agents" / "explorer.md").is_file()
    assert not (claude_directory / "agents" / "review-bugs.md").exists()
    assert os.access(installed_script, os.X_OK)
    assert settings["model"] == "local"
    assert len(hook_commands(settings["hooks"])) == 5
    assert user_skill.read_text(encoding="utf-8") != "my own skill\n"

    uninstalled = run_script("uninstall.sh", tmp_path)

    settings = json.loads((claude_directory / "settings.json").read_text(encoding="utf-8"))
    assert uninstalled.returncode == 0, uninstalled.stderr
    assert user_skill.read_text(encoding="utf-8") == "my own skill\n"
    assert not (claude_directory / "commands" / "feature.md").exists()
    assert not (claude_directory / "midnight-workflow").exists()
    assert hook_commands(settings["hooks"]) == ["echo mine"]


@pytest.mark.skipif(not IS_POSIX, reason="the installed hook runs with the Ubuntu layout")
def test_installed_stop_hook_runs_from_the_install_layout(tmp_path: Path):
    run_script("install.sh", tmp_path)
    hook_path = tmp_path / ".claude" / "midnight-workflow" / "scripts" / "hooks" / "next_step.py"

    completed = subprocess.run(
        [str(hook_path)],
        input=json.dumps({"cwd": str(tmp_path)}),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
