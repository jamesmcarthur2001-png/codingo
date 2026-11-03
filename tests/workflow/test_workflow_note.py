import sys
from collections.abc import Callable
from pathlib import Path

import pytest

import workflow_note
from conftest import git


@pytest.fixture
def feedback_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "feedback"
    monkeypatch.setenv("WORKFLOW_FEEDBACK_DIR", str(folder))
    return folder


def run_note(monkeypatch: pytest.MonkeyPatch, *arguments: str) -> int:
    monkeypatch.setattr(sys, "argv", ["workflow_note.py", *arguments])
    return workflow_note.main()


def test_workflow_note_appends_to_the_branch_file(git_repository: Path, feedback_folder: Path, monkeypatch: pytest.MonkeyPatch):
    git(git_repository, "checkout", "--quiet", "-b", "BTRC-1234-csv/export")
    monkeypatch.chdir(git_repository)

    exit_code = run_note(monkeypatch, "--kind", "script", "--source", "review_round.py", "--what", "capture refused a quoted ## line", "--suggestion", "skip lines inside code fences")

    notes = (feedback_folder / "BTRC-1234-csv-export" / "orchestrator.md").read_text(encoding="utf-8")
    assert exit_code == 0
    assert "· script · review_round.py" in notes
    assert "- Suggestion: skip lines inside code fences" in notes


def test_workflow_note_keeps_earlier_notes(git_repository: Path, feedback_folder: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(git_repository)
    run_note(monkeypatch, "--what", "first", "--suggestion", "one")

    run_note(monkeypatch, "--what", "second", "--suggestion", "two")

    notes = (feedback_folder / "master" / "orchestrator.md").read_text(encoding="utf-8")
    assert notes.index("first") < notes.index("second")


def test_workflow_note_names_the_active_feature(git_repository: Path, feedback_folder: Path, make_feature_state: Callable[..., Path], monkeypatch: pytest.MonkeyPatch):
    make_feature_state(git_repository, phase="GATE-B")
    monkeypatch.chdir(git_repository)

    run_note(monkeypatch, "--kind", "rule", "--source", "PY-75", "--what", "flagged a loop over a result set", "--suggestion", "skip the loop's iterable")

    assert "- Feature: BTRC-1234 · Phase: GATE-B" in (feedback_folder / "master" / "orchestrator.md").read_text(encoding="utf-8")


def test_workflow_note_without_a_suggestion_is_a_setup_error(git_repository: Path, feedback_folder: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(git_repository)

    exit_code = run_note(monkeypatch, "--what", "something")

    assert exit_code == 2
    assert not feedback_folder.exists()


def test_workflow_note_gives_each_writer_its_own_file(git_repository: Path, feedback_folder: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(git_repository)
    run_note(monkeypatch, "--author", "correctness-reviewer", "--what", "no EC-3 in the spec", "--suggestion", "ask for edge cases in the grill")

    run_note(monkeypatch, "--author", "finding-verifier-tests", "--what", "TS-29 text unclear", "--suggestion", "add an example")

    assert sorted(path.name for path in (feedback_folder / "master").iterdir()) == ["correctness-reviewer.md", "finding-verifier-tests.md"]


def test_workflow_note_show_prints_only_the_writers_own_notes(git_repository: Path, feedback_folder: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.chdir(git_repository)
    run_note(monkeypatch, "--author", "spec-reviewer", "--what", "reviewer only", "--suggestion", "x")
    capsys.readouterr()

    run_note(monkeypatch, "--show")

    assert "reviewer only" not in capsys.readouterr().out
