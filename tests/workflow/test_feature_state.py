from collections.abc import Callable
from pathlib import Path

import pytest

from feature_state import FeatureNotFoundError, FeatureState, find_active_feature, load_feature_state


def test_feature_state_field_reads_top_field(tmp_path: Path, make_feature_state: Callable[..., Path]):
    state = load_feature_state("BTRC-1234", make_feature_state(tmp_path))

    base = state.field("Base")

    assert base == "master"


def test_feature_state_missing_field_returns_empty_string(tmp_path: Path, make_feature_state: Callable[..., Path]):
    state = load_feature_state("BTRC-1234", make_feature_state(tmp_path))

    missing = state.field("Beatrice command")

    assert missing == ""


def test_feature_state_set_field_replaces_and_adds_fields(tmp_path: Path, make_feature_state: Callable[..., Path]):
    state = load_feature_state("BTRC-1234", make_feature_state(tmp_path))

    state.set_field("Phase", "GATE-A")
    state.set_field("Beatrice mode", "file")
    state.save()

    reloaded = FeatureState.load(state.path)
    assert reloaded.field("Phase") == "GATE-A"
    assert reloaded.field("Beatrice mode") == "file"
    assert reloaded.first_section_index() > reloaded.lines.index("Beatrice mode: file")


def test_feature_state_append_to_section_keeps_lines_inside_section(tmp_path: Path, make_feature_state: Callable[..., Path]):
    state = load_feature_state("BTRC-1234", make_feature_state(tmp_path))

    state.append_to_section("Commands", "- lint: npx nx lint api")
    state.append_to_section("Finish", "- push: done")

    assert state.section("Commands") == ["- lint: npx nx lint api"]
    assert state.section("Finish") == ["- push: done"]


def test_feature_state_append_to_missing_section_creates_it(tmp_path: Path, make_feature_state: Callable[..., Path]):
    state = load_feature_state("BTRC-1234", make_feature_state(tmp_path))

    state.append_to_section("Notes", "- first note")

    assert state.section("Notes") == ["- first note"]


def test_feature_state_record_failure_third_failure_blocks(tmp_path: Path, make_feature_state: Callable[..., Path]):
    state = load_feature_state("BTRC-1234", make_feature_state(tmp_path))

    counts = [state.record_failure("GATE-A-1") for _ in range(3)]

    assert counts == [1, 2, 3]
    assert state.status().startswith("BLOCKED")


def test_feature_state_record_failure_other_step_starts_again(tmp_path: Path, make_feature_state: Callable[..., Path]):
    state = load_feature_state("BTRC-1234", make_feature_state(tmp_path))
    state.record_failure("SLICE-1")
    state.record_failure("SLICE-1")

    count = state.record_failure("SLICE-2")

    assert count == 1
    assert not state.is_finished()


def test_feature_state_code_root_without_worktree_is_repository(tmp_path: Path, make_feature_state: Callable[..., Path]):
    state = load_feature_state("BTRC-1234", make_feature_state(tmp_path))

    code_root = state.code_root()

    assert code_root == tmp_path


def test_load_feature_state_missing_ticket_raises_feature_not_found_error(tmp_path: Path, make_feature_state: Callable[..., Path]):
    make_feature_state(tmp_path)

    with pytest.raises(FeatureNotFoundError, match="No state file"):
        load_feature_state("BTRC-9", tmp_path)


def test_find_active_feature_from_subdirectory_returns_feature(tmp_path: Path, make_feature_state: Callable[..., Path]):
    feature_directory = make_feature_state(tmp_path)
    subdirectory = tmp_path / "services" / "evermore"
    subdirectory.mkdir(parents=True)

    active = find_active_feature(subdirectory)

    assert active == feature_directory
