from collections.abc import Callable
from pathlib import Path

import pytest

from check_python_conventions import check_python_file

HEADER = '"""\nService manager for entities.\n\n:author: midnight-workflow\n:date: 16/10/2026\n"""\n'

COMPLIANT_SOURCE = HEADER + '''# ----- Imports ----- #

from app.models import Entity

# ----- Consts ----- #

PAGE_SIZE = 50

# ----- Classes ----- #


class EntityNotFoundError(Exception):
    """
    Raised when the entity does not exist.
    """

# ----- Functions ----- #


def read_entity_by_id(session: Session, entity_id: int) -> Entity:
    entity = session.get(Entity, entity_id)
    if entity is None:
        raise EntityNotFoundError(f"Entity {entity_id} was not found.")
    return entity


def find_entity_name(entity_id: int) -> str | None:
    if entity_id < 0:
        return None
    return "name"


def archive_entity(entity: Entity):
    if entity.is_archived:
        return
    entity.is_archived = True


def build_entity_query(
    session: Session,
    entity_type: str,
    page_size: int,
) -> Query:
    return session.query(
        entity_type,
        page_size,
        Entity,
    )
'''


def rule_ids(path: Path) -> list[str]:
    return [violation.rule_id for violation in check_python_file(path)]


def test_check_python_file_compliant_source_returns_no_violations(write_python_file: Callable[..., Path]):
    path = write_python_file(COMPLIANT_SOURCE)

    violations = check_python_file(path)

    assert violations == []


def test_check_python_file_empty_file_returns_no_violations(write_python_file: Callable[..., Path]):
    path = write_python_file("", "__init__.py")

    violations = check_python_file(path)

    assert violations == []


@pytest.mark.parametrize("snippet,expected_rule_id", [
    ("def save_entity(entity):\n    print(entity)\n", "PY-01"),
    ("def save_entity(entity: int) -> None:\n    print(entity)\n", "PY-02"),
    ("def save_entity(entity: int):\n    if entity > 0:\n        return None\n    print(entity)\n", "PY-03"),
    ("def save_entity(entity: int):\n    print(entity)\n    return\n", "PY-04"),
    ("__all__ = ['save_entity']\n", "PY-13"),
    ("def save_entity(entity: int):\n    '''Saves.'''\n", "PY-14"),
    ("raise ValueError('bad')\n", "PY-25"),
    ("class EntityMissing(Exception):\n    pass\n", "PY-26"),
    ("save_entity(first, second, third)\n", "PY-24"),
    ("save_entity(entity_identifier, replacement_value_for_entity_name)\n", "PY-24"),
])
def test_check_python_file_violating_snippet_reports_rule(
    write_python_file: Callable[..., Path],
    snippet: str,
    expected_rule_id: str,
):
    path = write_python_file(HEADER + "# ----- Imports ----- #\n\nimport os\n\n# ----- Functions ----- #\n\n\n" + snippet)

    reported_rule_ids = rule_ids(path)

    assert expected_rule_id in reported_rule_ids


@pytest.mark.parametrize("source,expected_rule_id", [
    ("import os\n", "PY-07"),
    ('"""\nNo author or date.\n"""\nimport os\n', "PY-07"),
    ('"""\nTwo-digit year.\n\n:author: midnight-workflow\n:date: 16/10/26\n"""\nimport os\n', "PY-07"),
    (HEADER + "\n# ----- Imports ----- #\n\nimport os\n", "PY-09"),
    (HEADER + "# ----- Imports ----- #\nimport os\n", "PY-09"),
    (HEADER + "# ----- Imports ----- #\n\nimport os\n# ----- Consts ----- #\n\nSIZE = 1\n", "PY-10"),
    (HEADER + "# ----- Imports ----- #\n\nimport os\n\n# ----- Functions ----- #\n\ndef run():\n    print(1)\n", "PY-11"),
    (HEADER + "# ----- imports ----- #\n\nimport os\n", "PY-08"),
    (HEADER + "# ---- Imports ---- #\n\nimport os\n", "PY-08"),
])
def test_check_python_file_bad_layout_reports_rule(
    write_python_file: Callable[..., Path],
    source: str,
    expected_rule_id: str,
):
    path = write_python_file(source)

    reported_rule_ids = rule_ids(path)

    assert expected_rule_id in reported_rule_ids


def test_check_python_file_blank_line_between_docstring_fields_reports_py15(write_python_file: Callable[..., Path]):
    snippet = 'def save_entity(entity: int) -> int:\n    """\n    Saves.\n\n    :param entity: Id.\n\n    :return: Id.\n    """\n    return entity\n'
    path = write_python_file(HEADER + "# ----- Imports ----- #\n\nimport os\n\n# ----- Functions ----- #\n\n\n" + snippet)

    reported_rule_ids = rule_ids(path)

    assert "PY-15" in reported_rule_ids


def test_check_python_file_init_docstring_reports_py16(write_python_file: Callable[..., Path]):
    snippet = 'class Store:\n    """\n    Store.\n    """\n\n    def __init__(self):\n        """\n        Builds.\n        """\n        self.items = 1\n'
    path = write_python_file(HEADER + "# ----- Imports ----- #\n\nimport os\n\n# ----- Classes ----- #\n\n\n" + snippet)

    reported_rule_ids = rule_ids(path)

    assert "PY-16" in reported_rule_ids


def test_check_python_file_utf8_bom_reports_py00(tmp_path: Path):
    path = tmp_path / "module.py"
    path.write_bytes(b"\xef\xbb\xbf" + COMPLIANT_SOURCE.encode("utf-8"))

    reported_rule_ids = rule_ids(path)

    assert reported_rule_ids == ["PY-00"]


def test_check_python_file_test_module_skips_layout_rules(write_python_file: Callable[..., Path]):
    path = write_python_file(
        "import pytest\n\n@pytest.mark.parametrize('value,expected', [(1, 2), (2, 3)])\ndef test_increment(value, expected):\n    assert value + 1 == expected\n",
        "test_increment.py",
    )

    violations = check_python_file(path)

    assert violations == []


def test_check_python_file_syntax_error_reports_syntax_rule(write_python_file: Callable[..., Path]):
    path = write_python_file("def broken(:\n")

    reported_rule_ids = rule_ids(path)

    assert reported_rule_ids == ["PY-SYNTAX"]


def test_check_python_file_get_prefix_on_function_reports_py62(write_python_file: Callable[..., Path]):
    path = write_python_file(COMPLIANT_SOURCE + "\n\ndef get_entity_by_id(entity_id: int) -> int:\n    return entity_id\n")

    violations = check_python_file(path)

    assert [violation.rule_id for violation in violations] == ["PY-62"]
    assert "entity_by_id" in violations[0].message


def test_check_python_file_get_prefix_in_test_file_reports_py62(write_python_file: Callable[..., Path]):
    path = write_python_file("def get_entity():\n    return 1\n", "test_entities.py")

    reported_rule_ids = rule_ids(path)

    assert reported_rule_ids == ["PY-62"]


@pytest.mark.parametrize(
    "expression",
    [
        'name or "Unknown"',
        "items or []",
        'email or f"{user_id}@example.com"',
        "value or default",
        "entity_by_id(1) or fallback",
    ],
)
def test_check_python_file_or_used_as_default_reports_py56(write_python_file: Callable[..., Path], expression: str):
    path = write_python_file(f"def test_default(name, items, email, user_id, value, default, fallback):\n    result = {expression}\n    assert result\n", "test_defaults.py")

    reported_rule_ids = rule_ids(path)

    assert reported_rule_ids == ["PY-56"]


@pytest.mark.parametrize(
    "statement",
    [
        "if name is None or len(items) == 0:\n        return",
        "is_empty = is_new or len(items) == 0",
        "is_test = path.startswith('test_') or path == 'conftest.py'",
        "while not done or retries > 0:\n        break",
        "assert is_ready or is_skipped",
        "has_items = not items or is_forced",
    ],
)
def test_check_python_file_or_used_as_condition_returns_no_violations(write_python_file: Callable[..., Path], statement: str):
    path = write_python_file(f"def test_condition(name, items, is_new, path, done, retries, is_ready, is_skipped, is_forced):\n    {statement}\n", "test_conditions.py")

    violations = check_python_file(path)

    assert violations == []
