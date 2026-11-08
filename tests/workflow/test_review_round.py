import json
from collections.abc import Callable
from pathlib import Path

import pytest

import review_round
from conftest import git
from feature_state import FeatureState

CONVENTIONS_REVIEW = """# Conventions review, round 1

## app/entities.py:3 | PY-23
`if not rows:` on a list. Use `if len(rows) == 0:`.

## no file | no rule
Something general.

Done: 2 finding(s)
"""
EMPTY_REVIEW = "# {title} review, round 1\n\nDone: 0 finding(s)\n"
CONVENTIONS_VERIFY = """# Verify conventions, round 1

## C1-1 | invalid
Evidence: `rows` is a bool flag here, line 3.

## C1-2 | unsure
Couldn't tell.
"""
SOURCED_TRIAGE = """## Round 1
| # | Source | Verdict | File:line | Rule | Finding | Decision | Reason |
|---|---|---|---|---|---|---|---|
| C1-1 | conventions | invalid | app/entities.py:3 | PY-23 | truthy check | dismiss | rows is a bool flag here |
| C1-2 | conventions | unsure | - | - | general | fix | |
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


def state_of(feature_directory: Path) -> FeatureState:
    return FeatureState.load(feature_directory / "state.md")


def turn_on_playwright(feature_directory: Path):
    state = state_of(feature_directory)
    state.append_to_section("Frontend", "- Playwright reviewer: yes")
    state.save()


def run_main(monkeypatch: pytest.MonkeyPatch, *arguments: str) -> int:
    monkeypatch.setattr("sys.argv", ["review_round.py", *arguments])
    return review_round.main()


def write_review(review_feature: Path, name: str, text: str):
    (review_feature / "review" / name).write_text(text, encoding="utf-8")


def complete_round_one(review_feature: Path, monkeypatch: pytest.MonkeyPatch):
    write_review(review_feature, "conventions-1.md", CONVENTIONS_REVIEW)
    for review_source in ("correctness", "tests", "spec"):
        write_review(review_feature, f"{review_source}-1.md", EMPTY_REVIEW.format(title=review_source))
        run_main(monkeypatch, "capture", "BTRC-1234", "1", "--source", review_source)
    run_main(monkeypatch, "capture", "BTRC-1234", "1", "--source", "conventions")
    write_review(review_feature, "verify-conventions-1.md", CONVENTIONS_VERIFY)


def test_parse_reviewer_findings_reads_headers_and_text():
    findings = review_round.parse_reviewer_findings(review_round.numbered_review(CONVENTIONS_REVIEW, "conventions", 1))

    assert [(finding.finding_id, finding.file, finding.line, finding.rule) for finding in findings] == [
        ("C1-1", "app/entities.py", 3, "PY-23"),
        ("C1-2", "", 0, ""),
    ]
    assert "len(rows) == 0" in findings[0].text
    assert "Done:" not in findings[1].text


def test_expected_lists_playwright_only_when_chosen(review_feature: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    run_main(monkeypatch, "expected", "BTRC-1234", "1")
    without = capsys.readouterr().out.strip()
    turn_on_playwright(review_feature)
    run_main(monkeypatch, "expected", "BTRC-1234", "1")
    with_playwright = capsys.readouterr().out.strip()

    assert (without, with_playwright) == ("correctness conventions tests spec", "correctness conventions tests spec playwright")


def test_capture_stores_the_flagged_line_text(review_feature: Path, monkeypatch: pytest.MonkeyPatch):
    write_review(review_feature, "conventions-1.md", CONVENTIONS_REVIEW)

    exit_code = run_main(monkeypatch, "capture", "BTRC-1234", "1", "--source", "conventions")

    records = json.loads((review_feature / "review" / "conventions-1.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert records[0]["line_text"] == "if not rows:"


def test_capture_numbers_the_findings_in_the_reviewer_file(review_feature: Path, monkeypatch: pytest.MonkeyPatch):
    write_review(review_feature, "conventions-1.md", CONVENTIONS_REVIEW)

    run_main(monkeypatch, "capture", "BTRC-1234", "1", "--source", "conventions")

    numbered = (review_feature / "review" / "conventions-1.md").read_text(encoding="utf-8")
    assert "## C1-1 | app/entities.py:3 | PY-23" in numbered
    assert "## C1-2 | no file | no rule" in numbered


def test_capture_again_keeps_the_numbers_it_gave(review_feature: Path, monkeypatch: pytest.MonkeyPatch):
    write_review(review_feature, "conventions-1.md", CONVENTIONS_REVIEW)
    run_main(monkeypatch, "capture", "BTRC-1234", "1", "--source", "conventions")
    first = (review_feature / "review" / "conventions-1.md").read_text(encoding="utf-8")

    run_main(monkeypatch, "capture", "BTRC-1234", "1", "--source", "conventions")

    assert (review_feature / "review" / "conventions-1.md").read_text(encoding="utf-8") == first


@pytest.mark.parametrize("review_text,expected_problem", [
    (CONVENTIONS_REVIEW.replace("Done: 2 finding(s)\n", ""), "no `Done:"),
    (CONVENTIONS_REVIEW.replace("Done: 2", "Done: 3"), "`Done: 3` but 2"),
    (CONVENTIONS_REVIEW.replace("## no file | no rule", "## no file"), "not a finding header"),
    (CONVENTIONS_REVIEW.replace("## no file | no rule", "## K1-2 | no file | no rule"), "should start with C1-"),
])
def test_capture_refuses_an_incomplete_reviewer_file(
    review_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    review_text: str,
    expected_problem: str,
):
    write_review(review_feature, "conventions-1.md", review_text)

    exit_code = run_main(monkeypatch, "capture", "BTRC-1234", "1", "--source", "conventions")

    assert exit_code == 1
    assert expected_problem in capsys.readouterr().out
    assert not (review_feature / "review" / "conventions-1.json").exists()


def test_capture_of_a_missing_file_three_times_blocks_the_feature(review_feature: Path, monkeypatch: pytest.MonkeyPatch):
    for _ in range(3):
        run_main(monkeypatch, "capture", "BTRC-1234", "1", "--source", "tests")

    assert state_of(review_feature).status().startswith("BLOCKED")


def test_verify_check_wants_one_verdict_per_finding(review_feature: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    write_review(review_feature, "conventions-1.md", CONVENTIONS_REVIEW)
    run_main(monkeypatch, "capture", "BTRC-1234", "1", "--source", "conventions")
    write_review(review_feature, "verify-conventions-1.md", CONVENTIONS_VERIFY.replace("## C1-2 | unsure\nCouldn't tell.\n", ""))
    capsys.readouterr()

    exit_code = run_main(monkeypatch, "verify-check", "BTRC-1234", "1", "--source", "conventions")

    assert exit_code == 1
    assert "C1-2 has no verdict" in capsys.readouterr().out


def test_verify_check_needs_no_verifier_for_zero_findings(review_feature: Path, monkeypatch: pytest.MonkeyPatch):
    write_review(review_feature, "spec-1.md", EMPTY_REVIEW.format(title="Spec"))
    run_main(monkeypatch, "capture", "BTRC-1234", "1", "--source", "spec")

    exit_code = run_main(monkeypatch, "verify-check", "BTRC-1234", "1", "--source", "spec")

    assert exit_code == 0


def test_triage_check_passes_when_rows_follow_the_verdicts(review_feature: Path, monkeypatch: pytest.MonkeyPatch):
    complete_round_one(review_feature, monkeypatch)
    write_review(review_feature, "triage.md", SOURCED_TRIAGE)

    exit_code = run_main(monkeypatch, "triage-check", "BTRC-1234", "1")

    assert exit_code == 0


@pytest.mark.parametrize("triage_text,expected_problem", [
    (SOURCED_TRIAGE.replace("| C1-2 | conventions | unsure | - | - | general | fix | |\n", ""), "C1-2: no row"),
    (SOURCED_TRIAGE.replace("invalid | app/entities.py:3 | PY-23 | truthy check | dismiss", "invalid | app/entities.py:3 | PY-23 | truthy check | fix"), "verdict `invalid` needs Decision dismiss"),
    (SOURCED_TRIAGE.replace("| unsure | - | - | general | fix | |", "| sure | - | - | general | fix | |"), "the verifier said `unsure`"),
    (SOURCED_TRIAGE.replace("| general | fix | |", "| general | dismiss | |"), "a dismiss needs a Reason"),
])
def test_triage_check_refuses_rows_that_dont_follow_the_verdict(
    review_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    triage_text: str,
    expected_problem: str,
):
    complete_round_one(review_feature, monkeypatch)
    write_review(review_feature, "triage.md", triage_text)
    capsys.readouterr()

    exit_code = run_main(monkeypatch, "triage-check", "BTRC-1234", "1")

    assert exit_code == 1
    assert expected_problem in capsys.readouterr().out


def test_triage_check_refuses_a_round_with_a_reviewer_missing(review_feature: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    write_review(review_feature, "conventions-1.md", CONVENTIONS_REVIEW)
    run_main(monkeypatch, "capture", "BTRC-1234", "1", "--source", "conventions")
    write_review(review_feature, "verify-conventions-1.md", CONVENTIONS_VERIFY)
    write_review(review_feature, "triage.md", SOURCED_TRIAGE)
    capsys.readouterr()

    exit_code = run_main(monkeypatch, "triage-check", "BTRC-1234", "1")

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "correctness: not captured" in output


def test_dismissed_rows_feed_the_dismissed_memory_per_source(review_feature: Path, monkeypatch: pytest.MonkeyPatch):
    complete_round_one(review_feature, monkeypatch)
    write_review(review_feature, "triage.md", SOURCED_TRIAGE)

    dismissed = review_round.sync_dismissed(state_of(review_feature))

    assert [(dismissal.source, dismissal.finding_id) for dismissal in dismissed] == [("conventions", "C1-1")]
    assert review_round.find_dismissal(dismissed, "app/entities.py", "PY-23", "if not rows:", "conventions") is not None
    assert review_round.find_dismissal(dismissed, "app/entities.py", "PY-23", "if not rows:", "correctness") is None


def test_capture_notes_findings_dismissed_in_an_earlier_round(review_feature: Path, monkeypatch: pytest.MonkeyPatch):
    complete_round_one(review_feature, monkeypatch)
    write_review(review_feature, "triage.md", SOURCED_TRIAGE)
    write_review(review_feature, "conventions-2.md", CONVENTIONS_REVIEW.replace("round 1", "round 2"))

    run_main(monkeypatch, "capture", "BTRC-1234", "2", "--source", "conventions")

    second_review = (review_feature / "review" / "conventions-2.md").read_text(encoding="utf-8")
    assert "## Dismissed in earlier rounds" in second_review
    assert "C2-1: dismissed in round 1, because rows is a bool flag here" in second_review

