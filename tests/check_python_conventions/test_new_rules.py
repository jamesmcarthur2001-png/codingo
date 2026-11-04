from collections.abc import Callable
from pathlib import Path

import pytest

from check_python_conventions import check_python_file

HEADER = '"""\nEntities.\n\n:author: claude-workflow\n:date: 16/10/2026\n"""\n'
FUNCTIONS = HEADER + "# ----- Functions ----- #\n\n\n"


def rule_ids(path: Path, base_source: str | None = None) -> list[str]:
    return [violation.rule_id for violation in check_python_file(path, base_source)]


def test_check_python_file_shebang_before_page_docstring_is_allowed(write_python_file: Callable[..., Path]):
    path = write_python_file("#!/usr/bin/env python3\n" + HEADER + "# ----- Imports ----- #\n\nimport os\n")

    violations = check_python_file(path)

    assert violations == []


def test_check_python_file_bool_function_existing_in_base_is_not_new(write_python_file: Callable[..., Path]):
    source = FUNCTIONS + "def name_valid(name: str, strict: bool) -> bool:\n    return name != \"\"\n"
    base_source = FUNCTIONS + "def name_valid(name: str) -> bool:\n    return name != \"\"\n"
    path = write_python_file(source)

    reported_rule_ids = rule_ids(path, base_source)

    assert "PY-85" not in reported_rule_ids


def test_check_python_file_bool_method_overriding_a_framework_base_is_allowed(write_python_file: Callable[..., Path]):
    source = HEADER + "# ----- Imports ----- #\n\nfrom framework import ModelView\n\n# ----- Classes ----- #\n\n\nclass EntityView(ModelView):\n    \"\"\"\n    The entity admin view.\n    \"\"\"\n    def permission(self) -> bool:\n        \"\"\"\n        Allow the view.\n        \"\"\"\n        return True\n"
    path = write_python_file(source)

    reported_rule_ids = rule_ids(path)

    assert "PY-85" not in reported_rule_ids


@pytest.mark.parametrize("name", ["name_valid", "_check_name", "validate_name"])
def test_check_python_file_bool_function_without_a_question_name_reports_py85(write_python_file: Callable[..., Path], name: str):
    path = write_python_file(f"def {name}(name: str) -> bool:\n    return name != \"\"\n", "test_names.py")

    reported_rule_ids = rule_ids(path)

    assert reported_rule_ids == ["PY-85"]


@pytest.mark.parametrize("name", ["is_name_valid", "_is_name_valid", "has_children", "can_archive", "should_retry"])
def test_check_python_file_bool_function_with_a_question_name_is_allowed(write_python_file: Callable[..., Path], name: str):
    path = write_python_file(f"def {name}(name: str) -> bool:\n    return name != \"\"\n", "test_names.py")

    reported_rule_ids = rule_ids(path)

    assert reported_rule_ids == []


@pytest.mark.parametrize("name", ["_reject_duplicate_name", "accept_invitation", "_reject"])
def test_check_python_file_reject_or_accept_function_reports_py86(write_python_file: Callable[..., Path], name: str):
    path = write_python_file(f"def {name}(name: str):\n    return name\n", "test_names.py")

    reported_rule_ids = rule_ids(path)

    assert reported_rule_ids == ["PY-86"]


@pytest.mark.parametrize("source", [
    "class EntityReader:\n    def get_entity(self):\n        return 1\n",
    "def get_session():\n    return 1\n",
    "def rejection_reason(name: str):\n    return name\n",
])
def test_check_python_file_get_and_lookalike_names_are_allowed(write_python_file: Callable[..., Path], source: str):
    path = write_python_file(source, "test_names.py")

    reported_rule_ids = rule_ids(path)

    assert reported_rule_ids == []


@pytest.mark.parametrize(
    "statement",
    [
        "return started or forced",
        "enabled_value = enabled or debug",
        "if (name or default) is None:\n        return",
    ],
)
def test_check_python_file_or_of_bool_annotated_names_returns_no_violations(write_python_file: Callable[..., Path], statement: str):
    source = f"def test_flags(started: bool, forced: bool, enabled: bool, debug: bool):\n    {statement}\n"
    if "name or default" in statement:
        source = f"def test_flags(name: bool, default: bool):\n    {statement}\n"
    path = write_python_file(source, "test_flags.py")

    reported_rule_ids = rule_ids(path)

    assert reported_rule_ids == []


@pytest.mark.parametrize(
    "expression",
    [
        'verbose and (items or "none")',
        'name if is_known else (alias or "unknown")',
        "[item for item in (items or [])]",
    ],
)
def test_check_python_file_or_default_inside_other_expressions_reports_py56(write_python_file: Callable[..., Path], expression: str):
    path = write_python_file(f"def test_default(verbose, items, name, is_known, alias):\n    result = {expression}\n    assert result\n", "test_inner.py")

    reported_rule_ids = rule_ids(path)

    assert reported_rule_ids == ["PY-56"]


def test_check_python_file_or_in_comprehension_filter_returns_no_violations(write_python_file: Callable[..., Path]):
    path = write_python_file("def test_filter(items):\n    result = [item for item in items if item.is_new or item.is_dirty]\n    assert result\n", "test_filter.py")

    reported_rule_ids = rule_ids(path)

    assert reported_rule_ids == []


def test_check_python_file_multiline_call_violation_spans_the_whole_call(write_python_file: Callable[..., Path]):
    source = FUNCTIONS + "def build(name: str) -> dict[str, str]:\n    return dict(name=name, kind='a',\n        owner='b', status='c')\n"
    path = write_python_file(source)

    violation = next(violation for violation in check_python_file(path) if violation.rule_id == "PY-24")

    assert (violation.line, violation.last_line) == (11, 12)


@pytest.mark.parametrize("source,expected_rule_id", [
    ("class EntityCreator:\n    def __init__(self, session):\n        self._reader = EntityReader(session)\n", "PY-74"),
    ("class EntityReader:\n    def entities(self, ids):\n        for entity_id in ids:\n            self._session.get(Entity, entity_id)\n", "PY-75"),
    ("class EntityReader:\n    def entities(self, ids):\n        return [self.entity_by_id(entity_id) for entity_id in ids]\n", "PY-75"),
    ("class EntityCreator:\n    def create(self, name):\n        raise ConflictError(f\"Failed to create entity {name}\")\n", "PY-77"),
    ("class EntityPayload(BaseModel):\n    extra: dict[str, Any]\n", "PY-83"),
])
def test_check_python_file_manager_and_model_rules(write_python_file: Callable[..., Path], source: str, expected_rule_id: str):
    path = write_python_file(source, "test_managers.py")

    reported_rule_ids = rule_ids(path)

    assert expected_rule_id in reported_rule_ids


@pytest.mark.parametrize("source", [
    "class EntityReader:\n    def entities(self):\n        for entity in self._session.exec(select(Entity)):\n            print(entity)\n",
    "class EntityCreator:\n    def __init__(self, reader: EntityReader):\n        self._reader = reader\n",
    "def build_readers(session):\n    return EntityReader(session)\n",
    "class EntityPayload(BaseModel):\n    extra: dict[str, JsonValue]\n",
])
def test_check_python_file_manager_and_model_rules_allow_the_good_forms(write_python_file: Callable[..., Path], source: str):
    path = write_python_file(source, "test_managers.py")

    reported_rule_ids = rule_ids(path)

    assert not set(reported_rule_ids) & {"PY-74", "PY-75", "PY-77", "PY-83"}
