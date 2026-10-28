from collections.abc import Callable
from pathlib import Path

from mypy_strict import filter_mypy_output

SOURCE = '''def save(x: int):
    print(x)


def compute(x: int):
    return x + 1


def stream(x: int):
    yield x


def bare():
    print(1)
'''


def test_filter_mypy_output_none_returning_function_drops_error(write_python_file: Callable[..., Path]):
    path = write_python_file(SOURCE)
    output_lines = [f"{path}:1: error: Function is missing a return type annotation  [no-untyped-def]"]

    kept_lines = filter_mypy_output(output_lines)

    assert kept_lines == []


def test_filter_mypy_output_value_returning_function_keeps_error(write_python_file: Callable[..., Path]):
    path = write_python_file(SOURCE)
    output_lines = [f"{path}:5: error: Function is missing a return type annotation  [no-untyped-def]"]

    kept_lines = filter_mypy_output(output_lines)

    assert kept_lines == output_lines


def test_filter_mypy_output_generator_function_keeps_error(write_python_file: Callable[..., Path]):
    path = write_python_file(SOURCE)
    output_lines = [f"{path}:9: error: Function is missing a return type annotation  [no-untyped-def]"]

    kept_lines = filter_mypy_output(output_lines)

    assert kept_lines == output_lines


def test_filter_mypy_output_suppressed_error_drops_its_note(write_python_file: Callable[..., Path]):
    path = write_python_file(SOURCE)
    output_lines = [
        f"{path}:13: error: Function is missing a return type annotation  [no-untyped-def]",
        f'{path}:13: note: Use "-> None" if function does not return a value',
    ]

    kept_lines = filter_mypy_output(output_lines)

    assert kept_lines == []


def test_filter_mypy_output_other_errors_are_kept(write_python_file: Callable[..., Path]):
    path = write_python_file(SOURCE)
    output_lines = [f"{path}:2: error: Function is missing a type annotation for one or more arguments  [no-untyped-def]"]

    kept_lines = filter_mypy_output(output_lines)

    assert kept_lines == output_lines
