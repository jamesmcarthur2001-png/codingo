from collections.abc import Callable
from pathlib import Path

import pytest

NEW_TEST_SOURCE = "def test_read_entity_missing_id_raises_entity_not_found_error():\n    assert True\n"
FRONTEND_TEST_SOURCE = "it('shows a loading state while fetching entities', () => {\n  expect(1).toBe(1)\n})\n"


@pytest.fixture
def make_feature(tmp_path: Path) -> Callable[[str | None], Path]:
    def _make(test_plan: str | None) -> Path:
        features_directory = tmp_path / "docs" / "features"
        (features_directory / "entity-reader").mkdir(parents=True)
        (features_directory / ".active").write_text("entity-reader\n", encoding="utf-8")
        if test_plan is not None:
            (features_directory / "entity-reader" / "test-plan.md").write_text(test_plan, encoding="utf-8")
        return tmp_path

    return _make


def write_payload(project: Path, file_name: str, content: str) -> dict[str, object]:
    return {
        "tool_name": "Write",
        "cwd": str(project),
        "tool_input": {"file_path": str(project / "tests" / "entities" / file_name), "content": content},
    }


def test_guard_test_plan_no_active_feature_allows(tmp_path: Path, run_hook: Callable[..., object]):
    payload = write_payload(tmp_path, "test_reader.py", NEW_TEST_SOURCE)

    completed = run_hook("guard_test_plan.py", payload)

    assert completed.returncode == 0


def test_guard_test_plan_missing_test_plan_blocks(make_feature: Callable[..., Path], run_hook: Callable[..., object]):
    project = make_feature(None)

    completed = run_hook("guard_test_plan.py", write_payload(project, "test_reader.py", NEW_TEST_SOURCE))

    assert completed.returncode == 2
    assert "test-plan.md" in completed.stderr


def test_guard_test_plan_unplanned_test_blocks_with_its_name(make_feature: Callable[..., Path], run_hook: Callable[..., object]):
    project = make_feature("| T-1 | test_something_else | ... |\n")

    completed = run_hook("guard_test_plan.py", write_payload(project, "test_reader.py", NEW_TEST_SOURCE))

    assert completed.returncode == 2
    assert "test_read_entity_missing_id_raises_entity_not_found_error" in completed.stderr


def test_guard_test_plan_planned_test_allows(make_feature: Callable[..., Path], run_hook: Callable[..., object]):
    project = make_feature("| T-1 | test_read_entity_missing_id_raises_entity_not_found_error | ... |\n")

    completed = run_hook("guard_test_plan.py", write_payload(project, "test_reader.py", NEW_TEST_SOURCE))

    assert completed.returncode == 0


def test_guard_test_plan_unplanned_frontend_test_blocks(make_feature: Callable[..., Path], run_hook: Callable[..., object]):
    project = make_feature("| T-1 | test_other | ... |\n")

    completed = run_hook("guard_test_plan.py", write_payload(project, "EntityList.spec.ts", FRONTEND_TEST_SOURCE))

    assert completed.returncode == 2
    assert "shows a loading state while fetching entities" in completed.stderr


def test_guard_test_plan_unplanned_browser_test_blocks_with_its_name(
    make_feature: Callable[..., Path],
    run_hook: Callable[..., object],
):
    project = make_feature("| T-1 | test_other | ... |\n")
    content = "test.describe('Entities', () => {\n  test('user creates an entity and sees it in the list', async ({ page }) => {\n    await test.step('open the create dialog', async () => {})\n  })\n})\n"
    payload = write_payload(project, "create-entity.spec.ts", content)

    completed = run_hook("guard_test_plan.py", payload)

    assert completed.returncode == 2
    assert "user creates an entity and sees it in the list" in completed.stderr


@pytest.mark.parametrize("helper_call", [
    "test.describe('Entities', () => {})",
    "test.step('open the create dialog', async () => {})",
    "test.beforeEach(async ({ page }) => {})",
    "test.use({ locale: 'en-US' })",
])
def test_guard_test_plan_playwright_helper_calls_are_not_tests(
    make_feature: Callable[..., Path],
    run_hook: Callable[..., object],
    helper_call: str,
):
    project = make_feature(None)
    payload = write_payload(project, "create-entity.spec.ts", helper_call + "\n")

    completed = run_hook("guard_test_plan.py", payload)

    assert completed.returncode == 0


def test_guard_test_plan_planned_browser_test_allows(make_feature: Callable[..., Path], run_hook: Callable[..., object]):
    project = make_feature("| T-7 | browser | `user creates an entity and sees it in the list` | ... |\n")
    content = "test.describe('Entities', () => {\n  test('user creates an entity and sees it in the list', async ({ page }) => {})\n})\n"
    payload = write_payload(project, "create-entity.spec.ts", content)

    completed = run_hook("guard_test_plan.py", payload)

    assert completed.returncode == 0


def test_guard_test_plan_edit_of_existing_test_allows(make_feature: Callable[..., Path], run_hook: Callable[..., object]):
    project = make_feature(None)
    payload = {
        "tool_name": "Edit",
        "cwd": str(project),
        "tool_input": {
            "file_path": str(project / "tests" / "entities" / "test_reader.py"),
            "old_string": NEW_TEST_SOURCE,
            "new_string": NEW_TEST_SOURCE.replace("assert True", "assert 1 == 1"),
        },
    }

    completed = run_hook("guard_test_plan.py", payload)

    assert completed.returncode == 0


def test_guard_test_plan_non_test_file_allows(make_feature: Callable[..., Path], run_hook: Callable[..., object]):
    project = make_feature(None)
    payload = {
        "tool_name": "Write",
        "cwd": str(project),
        "tool_input": {"file_path": str(project / "app" / "reader.py"), "content": NEW_TEST_SOURCE},
    }

    completed = run_hook("guard_test_plan.py", payload)

    assert completed.returncode == 0


def test_guard_test_plan_reviewer_role_allows(make_feature: Callable[..., Path], run_hook: Callable[..., object]):
    project = make_feature(None)

    completed = run_hook(
        "guard_test_plan.py",
        write_payload(project, "test_reader.py", NEW_TEST_SOURCE),
        {"MIDNIGHT_ROLE": "reviewer"},
    )

    assert completed.returncode == 0
