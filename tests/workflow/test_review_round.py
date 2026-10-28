import json
from collections.abc import Callable
from pathlib import Path

import pytest

import gate_a
import review_round
from conftest import git
from feature_state import FeatureState

CONVENTIONS_REVIEW = """# Conventions review, round 1

## C1-1 | app/entities.py:3 | PY-23
`if not rows:` on a list. Use `if len(rows) == 0:`.

## C1-2 | no file | no rule
Something general.
"""
PLAYWRIGHT_REVIEW = """# Playwright review, round 1
App: http://localhost:5173 · backend: mocked

## P1-1 | frontend/src/views/Entities.vue:2 | REQ-3
Spinner never stops on an empty list. Screenshot: empty.png.
"""
SOURCED_TRIAGE = """## Round 1
| # | Source | Marks | File:line | Rule | Finding | Decision | Reason |
|---|---|---|---|---|---|---|---|
| R1-1 | beatrice | 2/2 | app/entities.py:3 | PY-23 | truthy check | fix | |
| C1-1 | conventions | - | app/entities.py:3 | PY-23 | truthy check | dismiss | rows is a bool flag here |
| P1-1 | playwright | - | frontend/src/views/Entities.vue:2 | REQ-3 | spinner | dismiss | screenshot shows the message |
"""


@pytest.fixture
def review_feature(git_repository: Path, make_feature_state: Callable[..., Path], monkeypatch: pytest.MonkeyPatch) -> Path:
    (git_repository / ".git" / "info" / "exclude").write_text("docs/features/\n", encoding="utf-8")
    (git_repository / "app").mkdir()
    (git_repository / "app" / "entities.py").write_text("a = 1\nb = 2\nif not rows:\n", encoding="utf-8")
    (git_repository / "frontend" / "src" / "views").mkdir(parents=True)
    (git_repository / "frontend" / "src" / "views" / "Entities.vue").write_text("<template>\n  <div />\n</template>\n", encoding="utf-8")
    git(git_repository, "add", "-A")
    git(git_repository, "commit", "--quiet", "-m", "app")
    git(git_repository, "checkout", "--quiet", "-b", "BTRC-1234-csv-export")
    feature_directory = make_feature_state(git_repository, phase="GATE-B")
    (feature_directory / "review").mkdir()
    monkeypatch.chdir(git_repository)
    return feature_directory


def state_of(feature_directory: Path) -> FeatureState:
    return FeatureState.load(feature_directory / "state.md")


def turn_on_playwright(feature_directory: Path):
    state = state_of(feature_directory)
    state.append_to_section("Frontend", "- Playwright reviewer: yes")
    state.save()


def run_main(monkeypatch: pytest.MonkeyPatch, *arguments: str) -> int:
    monkeypatch.setattr("sys.argv", ["review_round.py", *arguments])
    return review_round.main()


def test_parse_reviewer_findings_reads_headers_and_text():
    findings = review_round.parse_reviewer_findings(CONVENTIONS_REVIEW)

    assert [(finding.finding_id, finding.file, finding.line, finding.rule) for finding in findings] == [
        ("C1-1", "app/entities.py", 3, "PY-23"),
        ("C1-2", "", 0, ""),
    ]
    assert "len(rows) == 0" in findings[0].text


def test_capture_stores_the_flagged_line_text_per_source(review_feature: Path, monkeypatch: pytest.MonkeyPatch):
    (review_feature / "review" / "conventions-1.md").write_text(CONVENTIONS_REVIEW, encoding="utf-8")
    (review_feature / "review" / "playwright-1.md").write_text(PLAYWRIGHT_REVIEW, encoding="utf-8")

    exit_code = run_main(monkeypatch, "capture", "BTRC-1234", "1")

    conventions = json.loads((review_feature / "review" / "conventions-1.json").read_text(encoding="utf-8"))
    playwright = json.loads((review_feature / "review" / "playwright-1.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert conventions[0]["line_text"] == "if not rows:"
    assert playwright[0]["line_text"] == "<div />"
    assert state_of(review_feature).frontend_option("Playwright checked") != ""


def test_triage_with_source_column_keeps_dismissals_per_source(review_feature: Path, monkeypatch: pytest.MonkeyPatch):
    (review_feature / "review" / "conventions-1.md").write_text(CONVENTIONS_REVIEW, encoding="utf-8")
    (review_feature / "review" / "playwright-1.md").write_text(PLAYWRIGHT_REVIEW, encoding="utf-8")
    run_main(monkeypatch, "capture", "BTRC-1234", "1")
    code_root = review_feature.parent.parent.parent
    (code_root / "app" / "entities.py").write_text("shifted by a fix\na = 1\nb = 2\nif not rows:\n", encoding="utf-8")
    (review_feature / "review" / "triage.md").write_text(SOURCED_TRIAGE, encoding="utf-8")

    dismissed = gate_a.sync_dismissed(state_of(review_feature))

    assert sorted((dismissal.source, dismissal.finding_id) for dismissal in dismissed) == [("conventions", "C1-1"), ("playwright", "P1-1")]
    assert gate_a.find_dismissal(dismissed, "app/entities.py", "PY-23", "if not rows:", "conventions") is not None
    assert gate_a.find_dismissal(dismissed, "app/entities.py", "PY-23", "if not rows:", "beatrice") is None


def test_capture_notes_findings_dismissed_in_an_earlier_round(review_feature: Path, monkeypatch: pytest.MonkeyPatch):
    (review_feature / "review" / "conventions-1.md").write_text(CONVENTIONS_REVIEW, encoding="utf-8")
    run_main(monkeypatch, "capture", "BTRC-1234", "1")
    (review_feature / "review" / "triage.md").write_text(SOURCED_TRIAGE, encoding="utf-8")
    (review_feature / "review" / "conventions-2.md").write_text(CONVENTIONS_REVIEW.replace("C1-", "C2-").replace("round 1", "round 2"), encoding="utf-8")

    run_main(monkeypatch, "capture", "BTRC-1234", "2")

    second_review = (review_feature / "review" / "conventions-2.md").read_text(encoding="utf-8")
    assert "## Dismissed in earlier rounds" in second_review
    assert "C2-1: dismissed in round 1, because rows is a bool flag here" in second_review


def test_playwright_needed_is_no_when_the_grill_said_no(review_feature: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    run_main(monkeypatch, "playwright-needed", "BTRC-1234", "1")

    assert capsys.readouterr().out.strip() == "no"


def test_playwright_needed_in_round_one_is_yes(review_feature: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    turn_on_playwright(review_feature)

    run_main(monkeypatch, "playwright-needed", "BTRC-1234", "1")

    assert capsys.readouterr().out.strip() == "yes"


def test_playwright_needed_later_follows_frontend_changes(review_feature: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    turn_on_playwright(review_feature)
    vue_file = review_feature.parent.parent.parent / "frontend" / "src" / "views" / "Entities.vue"
    vue_file.write_text("<template>\n  <section />\n</template>\n", encoding="utf-8")
    (review_feature / "review" / "playwright-1.md").write_text(PLAYWRIGHT_REVIEW, encoding="utf-8")
    run_main(monkeypatch, "capture", "BTRC-1234", "1")
    capsys.readouterr()

    run_main(monkeypatch, "playwright-needed", "BTRC-1234", "2")
    unchanged = capsys.readouterr().out.strip()
    vue_file.write_text("<template>\n  <article />\n</template>\n", encoding="utf-8")
    run_main(monkeypatch, "playwright-needed", "BTRC-1234", "2")
    changed = capsys.readouterr().out.strip()

    assert (unchanged, changed) == ("no", "yes")


def test_gate_a_after_round_five_with_video_moves_to_video(review_feature: Path):
    state = state_of(review_feature)
    state.set_field("Round", "5")
    state.append_to_section("Frontend", "- Video: yes")
    state.save()
    (review_feature / "review" / "triage.md").write_text("## Round 5\n", encoding="utf-8")

    message = gate_a.record_gate_result(state_of(review_feature), True)

    assert state_of(review_feature).field("Phase") == "VIDEO"
    assert "Phase is now VIDEO" in message
