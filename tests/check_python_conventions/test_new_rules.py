from collections.abc import Callable
from pathlib import Path

import pytest

from check_python_conventions import check_python_file

HEADER = '"""\nEntities.\n\n:author: midnight-workflow\n:date: 16/10/2026\n"""\n'
FUNCTIONS = HEADER + "# ----- Functions ----- #\n\n\n"


def rule_ids(path: Path, base_source: str | None = None) -> list[str]:
    return [violation.rule_id for violation in check_python_file(path, base_source)]


def test_check_python_file_shebang_before_page_docstring_is_allowed(write_python_file: Callable[..., Path]):
    path = write_python_file("#!/usr/bin/env python3\n" + HEADER + "# ----- Imports ----- #\n\nimport os\n")

    violations = check_python_file(path)

    assert violations == []


def test_check_python_file_get_function_existing_in_base_is_not_new(write_python_file: Callable[..., Path]):
    source = FUNCTIONS + "def get_entity(entity_id: int, deleted: bool) -> int:\n    return entity_id\n"
    base_source = FUNCTIONS + "def get_entity(entity_id: int) -> int:\n    return entity_id\n"
    path = write_python_file(source)

    reported_rule_ids = rule_ids(path, base_source)

    assert "PY-62" not in reported_rule_ids


def test_check_python_file_get_method_overriding_a_framework_base_is_allowed(write_python_file: Callable[..., Path]):
    source = HEADER + "# ----- Imports ----- #\n\nfrom framework import ModelView\n\n# ----- Classes ----- #\n\n\nclass EntityView(ModelView):\n    \"\"\"\n    The entity admin view.\n    \"\"\"\n    def get_queryset(self) -> list[str]:\n        \"\"\"\n        List the rows.\n        \"\"\"\n        return []\n"
    path = write_python_file(source)

    reported_rule_ids = rule_ids(path)

    assert "PY-62" not in reported_rule_ids


def test_check_python_file_get_method_with_override_decorator_is_allowed(write_python_file: Callable[..., Path]):
    path = write_python_file("@override\ndef get_value():\n    return 1\n", "test_override.py")

    reported_rule_ids = rule_ids(path)

    assert reported_rule_ids == []


def test_check_python_file_new_get_method_of_local_class_reports_py62(write_python_file: Callable[..., Path]):
    path = write_python_file("class Store:\n    def get_entity(self):\n        return 1\n", "test_store.py")

    reported_rule_ids = rule_ids(path)

    assert reported_rule_ids == ["PY-62"]


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
