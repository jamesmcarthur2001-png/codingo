"""
Checks Python files against the house conventions that ruff and mypy cannot express.

:author: midnight-workflow
:date: 16/10/2026
"""
# ----- Imports ----- #

import argparse
import ast
import builtins
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# ----- Consts ----- #

UTF8_BOM = b"\xef\xbb\xbf"
BANNER_LIKE_PATTERN = re.compile(r"^\s*#\s*-{3,}")
BANNER_PATTERN = re.compile(r"^# ----- ([A-Z][A-Za-z0-9 ]*) ----- #$")
AUTHOR_PATTERN = re.compile(r"^:author: \S", re.MULTILINE)
DATE_PATTERN = re.compile(r"^:date: \d{2}/\d{2}/\d{4}$", re.MULTILINE)
DOCSTRING_QUOTE_LINES = ('"""', 'r"""')
DOCSTRING_FIELD_PREFIXES = (":param", ":return", ":raises")
IMPORTS_BANNER_NAME = "Imports"
CONSTS_BANNER_NAME = "Consts"
BLANK_LINES_BELOW_BANNER = {"Imports": 1, "Consts": 1}
DEFAULT_BLANK_LINES_BELOW_BANNER = 2
BLANK_LINES_ABOVE_BANNER = 1
MULTILINE_CALL_MIN_ARGUMENTS = 3
MULTILINE_CALL_MIN_ARGUMENTS_LENGTH = 50
SELF_ARGUMENT_NAMES = ("self", "cls")
EXCEPTION_NAME_SUFFIXES = ("Error", "Exception")
FUNCTION_NODE_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)
NESTED_SCOPE_NODE_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
DOCSTRING_OWNER_NODE_TYPES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
GET_PREFIX = "get_"
BOOLEAN_NAME_PREFIXES = ("is_", "has_", "should_", "can_", "was_", "were_", "does_", "did_")
BOOLEAN_CALL_NAMES = frozenset(
    {
        "isinstance",
        "issubclass",
        "hasattr",
        "callable",
        "any",
        "all",
        "bool",
        "startswith",
        "endswith",
        "match",
        "fullmatch",
        "exists",
        "is_file",
        "is_dir",
    },
)
CONDITION_PARENT_TYPES = (ast.If, ast.While, ast.IfExp, ast.Assert, ast.BoolOp, ast.comprehension)
BUILTIN_EXCEPTION_NAMES = frozenset(
    name
    for name, value in vars(builtins).items()
    if isinstance(value, type) and issubclass(value, BaseException)
)

# ----- Classes ----- #


@dataclass(frozen=True)
class Violation:
    """
    A single convention violation found in a file.
    """

    path: Path
    line: int
    rule_id: str
    message: str

    def format_for_output(self) -> str:
        return f"{self.path}:{self.line}: {self.rule_id} {self.message}"

# ----- Functions ----- #


def is_test_file(path: Path) -> bool:
    is_test_module = path.name.startswith("test_") or path.name == "conftest.py"
    return is_test_module or "tests" in path.parts


def build_parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def iter_own_body_nodes(function_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    """
    Collects every node inside a function body, without descending into nested scopes.

    :param function_node: The function whose own body is walked.
    :return: All nodes that belong to the function itself.
    """
    own_nodes: list[ast.AST] = []
    pending_nodes: list[ast.AST] = list(function_node.body)
    while len(pending_nodes) > 0:
        node = pending_nodes.pop()
        own_nodes.append(node)
        if isinstance(node, NESTED_SCOPE_NODE_TYPES):
            continue
        pending_nodes.extend(ast.iter_child_nodes(node))
    return own_nodes


def is_none_constant(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def function_returns_value(function_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """
    Tells whether a function returns a real value or is a generator.

    :param function_node: The function to inspect.
    :return: True when any own `return` carries a non-None value or the function yields.
    """
    for node in iter_own_body_nodes(function_node):
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            return True
        if isinstance(node, ast.Return) and node.value is not None and not is_none_constant(node.value):
            return True
    return False


def get_called_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def annotation_allows_none(annotation: ast.expr | None) -> bool:
    if annotation is None:
        return False
    for node in ast.walk(annotation):
        if is_none_constant(node) or get_called_name(node) == "Optional":
            return True
    return False


def get_docstring_node(node: ast.AST) -> ast.Constant | None:
    body = getattr(
        node,
        "body",
        None,
    )
    if not isinstance(body, list) or len(body) == 0:
        return None
    first_statement = body[0]
    if not isinstance(first_statement, ast.Expr):
        return None
    if isinstance(first_statement.value, ast.Constant) and isinstance(first_statement.value.value, str):
        return first_statement.value
    return None


def count_blank_lines_above(lines: list[str], index: int) -> int:
    blank_count = 0
    cursor = index - 1
    while cursor >= 0 and lines[cursor].strip() == "":
        blank_count += 1
        cursor -= 1
    return blank_count


def count_blank_lines_below(lines: list[str], index: int) -> int:
    blank_count = 0
    cursor = index + 1
    while cursor < len(lines) and lines[cursor].strip() == "":
        blank_count += 1
        cursor += 1
    return blank_count


def read_source_segment(
    line_bytes: list[bytes],
    start: tuple[int, int],
    end: tuple[int, int],
) -> str:
    """
    Reads source text between two AST positions (1-based lines, UTF-8 byte columns).

    :param line_bytes: The file's lines encoded as UTF-8.
    :param start: The (line, column) where the segment starts.
    :param end: The (line, column) where the segment ends.
    :return: The decoded text between the two positions.
    """
    start_line, start_column = start
    end_line, end_column = end
    if start_line == end_line:
        return line_bytes[start_line - 1][start_column:end_column].decode("utf-8")
    parts = [line_bytes[start_line - 1][start_column:]]
    parts.extend(line_bytes[start_line:end_line - 1])
    parts.append(line_bytes[end_line - 1][:end_column])
    return b"\n".join(parts).decode("utf-8")


def check_encoding(path: Path, raw_source: bytes) -> list[Violation]:
    if not raw_source.startswith(UTF8_BOM):
        return []
    violation = Violation(
        path,
        1,
        "PY-00",
        "File starts with a UTF-8 BOM; save it as UTF-8 without BOM.",
    )
    return [violation]


def check_parameter_annotations(
    path: Path,
    tree: ast.Module,
    parents: dict[ast.AST, ast.AST],
) -> list[Violation]:
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, FUNCTION_NODE_TYPES):
            continue
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if node.args.vararg is not None:
            arguments.append(node.args.vararg)
        if node.args.kwarg is not None:
            arguments.append(node.args.kwarg)
        is_method = isinstance(parents.get(node), ast.ClassDef)
        for position, argument in enumerate(arguments):
            if is_method and position == 0 and argument.arg in SELF_ARGUMENT_NAMES:
                continue
            if argument.annotation is not None:
                continue
            violation = Violation(
                path,
                argument.lineno,
                "PY-01",
                f"Parameter '{argument.arg}' of '{node.name}' has no type annotation.",
            )
            violations.append(violation)
    return violations


def check_none_returns(path: Path, tree: ast.Module) -> list[Violation]:
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, FUNCTION_NODE_TYPES):
            continue
        if is_none_constant(node.returns):
            violation = Violation(
                path,
                node.lineno,
                "PY-02",
                f"'{node.name}' is annotated '-> None'; omit the return annotation.",
            )
            violations.append(violation)
        may_return_none_value = annotation_allows_none(node.returns) and not is_none_constant(node.returns)
        for own_node in iter_own_body_nodes(node):
            if not isinstance(own_node, ast.Return) or not is_none_constant(own_node.value):
                continue
            if may_return_none_value:
                continue
            violation = Violation(
                path,
                own_node.lineno,
                "PY-03",
                "Write a bare 'return', never 'return None'.",
            )
            violations.append(violation)
        last_statement = node.body[-1]
        if isinstance(last_statement, ast.Return) and last_statement.value is None:
            violation = Violation(
                path,
                last_statement.lineno,
                "PY-04",
                f"Trailing bare 'return' at the end of '{node.name}' is not needed.",
            )
            violations.append(violation)
    return violations


def check_module_header(path: Path, tree: ast.Module) -> list[Violation]:
    docstring_node = get_docstring_node(tree)
    if docstring_node is None or docstring_node.lineno != 1:
        violation = Violation(
            path,
            1,
            "PY-07",
            "File must start with the page docstring (description, :author:, :date:).",
        )
        return [violation]
    violations: list[Violation] = []
    if AUTHOR_PATTERN.search(str(docstring_node.value)) is None:
        violation = Violation(
            path,
            1,
            "PY-07",
            "Missing ':author: NAME'.",
        )
        violations.append(violation)
    if DATE_PATTERN.search(str(docstring_node.value)) is None:
        violation = Violation(
            path,
            1,
            "PY-07",
            "Missing ':date: DD/MM/YYYY'.",
        )
        violations.append(violation)
    return violations


def check_docstring_layout(
    path: Path,
    docstring_node: ast.Constant,
    lines: list[str],
) -> list[Violation]:
    """
    Checks that a docstring's quotes sit on their own lines and its fields are contiguous.

    :param path: The file being checked.
    :param docstring_node: The docstring's string constant.
    :param lines: The file's source lines.
    :return: The layout violations of this docstring.
    """
    violations: list[Violation] = []
    end_line = docstring_node.end_lineno or docstring_node.lineno
    opening_line = lines[docstring_node.lineno - 1].strip()
    closing_line = lines[end_line - 1].strip()
    if opening_line not in DOCSTRING_QUOTE_LINES or closing_line != '"""':
        violation = Violation(
            path,
            docstring_node.lineno,
            "PY-14",
            'Docstring opening and closing """ must each be on their own line.',
        )
        violations.append(violation)
    docstring_lines = str(docstring_node.value).splitlines()
    field_indexes = [
        index
        for index, docstring_line in enumerate(docstring_lines)
        if docstring_line.strip().startswith(DOCSTRING_FIELD_PREFIXES)
    ]
    if len(field_indexes) < 2:
        return violations
    lines_between_fields = docstring_lines[field_indexes[0]:field_indexes[-1]]
    if any(docstring_line.strip() == "" for docstring_line in lines_between_fields):
        violation = Violation(
            path,
            docstring_node.lineno,
            "PY-15",
            "No blank lines allowed between :param / :return / :raises fields.",
        )
        violations.append(violation)
    return violations


def check_docstrings(path: Path, tree: ast.Module, lines: list[str]) -> list[Violation]:
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, DOCSTRING_OWNER_NODE_TYPES):
            continue
        docstring_node = get_docstring_node(node)
        if docstring_node is None:
            continue
        if isinstance(node, FUNCTION_NODE_TYPES) and node.name == "__init__":
            violation = Violation(
                path,
                docstring_node.lineno,
                "PY-16",
                "'__init__' must not have a docstring.",
            )
            violations.append(violation)
        violations += check_docstring_layout(
            path,
            docstring_node,
            lines,
        )
    return violations


def find_docstring_end_line(tree: ast.Module) -> int | None:
    docstring_node = get_docstring_node(tree)
    if docstring_node is None or docstring_node.lineno != 1:
        return None
    return docstring_node.end_lineno


def check_banner_spacing(
    path: Path,
    lines: list[str],
    index: int,
    section_name: str,
    docstring_end_line: int | None,
) -> list[Violation]:
    """
    Checks the blank lines around one well-formed section banner.

    :param path: The file being checked.
    :param lines: The file's source lines.
    :param index: The 0-based index of the banner line.
    :param section_name: The banner's section name.
    :param docstring_end_line: The page docstring's last line, when the file has one.
    :return: The spacing violations of this banner.
    """
    violations: list[Violation] = []
    line_number = index + 1
    if section_name == IMPORTS_BANNER_NAME:
        rule_id = "PY-09"
        if docstring_end_line is not None and line_number != docstring_end_line + 1:
            violation = Violation(
                path,
                line_number,
                rule_id,
                "Imports banner must be on the line right after the page docstring's closing quotes.",
            )
            violations.append(violation)
    else:
        rule_id = "PY-10" if section_name == CONSTS_BANNER_NAME else "PY-11"
        actual_above = count_blank_lines_above(lines, index)
        if actual_above != BLANK_LINES_ABOVE_BANNER:
            violation = Violation(
                path,
                line_number,
                rule_id,
                f"'{section_name}' banner needs exactly 1 blank line above (found {actual_above}).",
            )
            violations.append(violation)
    expected_below = BLANK_LINES_BELOW_BANNER.get(section_name, DEFAULT_BLANK_LINES_BELOW_BANNER)
    actual_below = count_blank_lines_below(lines, index)
    if actual_below != expected_below:
        violation = Violation(
            path,
            line_number,
            rule_id,
            f"'{section_name}' banner needs exactly {expected_below} blank line(s) below (found {actual_below}).",
        )
        violations.append(violation)
    return violations


def check_banners(path: Path, tree: ast.Module, lines: list[str]) -> list[Violation]:
    violations: list[Violation] = []
    docstring_end_line = find_docstring_end_line(tree)
    for index, line in enumerate(lines):
        if BANNER_LIKE_PATTERN.match(line) is None:
            continue
        banner_match = BANNER_PATTERN.match(line)
        if banner_match is None:
            violation = Violation(
                path,
                index + 1,
                "PY-08",
                "Section banner must be exactly '# ----- Name ----- #' with a capitalized name.",
            )
            violations.append(violation)
            continue
        violations += check_banner_spacing(
            path,
            lines,
            index,
            banner_match.group(1),
            docstring_end_line,
        )
    return violations


def check_dunder_all(path: Path, tree: ast.Module) -> list[Violation]:
    violations: list[Violation] = []
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                violation = Violation(
                    path,
                    node.lineno,
                    "PY-13",
                    "Do not define '__all__' in application packages.",
                )
                violations.append(violation)
    return violations


def is_exception_base(base: ast.expr) -> bool:
    base_name = get_called_name(base)
    if base_name is None:
        return False
    return base_name in BUILTIN_EXCEPTION_NAMES or base_name.endswith(EXCEPTION_NAME_SUFFIXES)


def check_exceptions(path: Path, tree: ast.Module) -> list[Violation]:
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and node.exc is not None:
            raised_name = get_called_name(node.exc)
            if raised_name is not None and raised_name in BUILTIN_EXCEPTION_NAMES:
                violation = Violation(
                    path,
                    node.lineno,
                    "PY-25",
                    f"Do not raise builtin '{raised_name}'; raise a custom domain exception.",
                )
                violations.append(violation)
        if not isinstance(node, ast.ClassDef) or node.name.endswith("Error"):
            continue
        if any(is_exception_base(base) for base in node.bases):
            violation = Violation(
                path,
                node.lineno,
                "PY-26",
                f"Exception class '{node.name}' must end with 'Error'.",
            )
            violations.append(violation)
    return violations


def is_inside_f_string(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, ast.JoinedStr):
            return True
        current = parents.get(current)
    return False


def is_argument_of_single_line_call(node: ast.Call, parents: dict[ast.AST, ast.AST]) -> bool:
    """
    Tells whether the call sits inside the arguments of an outer call on the same line.

    :param node: The call being checked.
    :param parents: Child-to-parent node map of the module.
    :return: True when an enclosing single-line call already owns this line.
    """
    child: ast.AST = node
    current = parents.get(node)
    while current is not None:
        if isinstance(current, ast.Call) and child is not current.func:
            has_arguments = len(current.args) + len(current.keywords) > 0
            if has_arguments and current.lineno == current.end_lineno == node.lineno:
                return True
        child = current
        current = parents.get(current)
    return False


def get_call_arguments(node: ast.Call) -> list[ast.expr | ast.keyword]:
    arguments: list[ast.expr | ast.keyword] = [*node.args, *node.keywords]
    return sorted(
        arguments,
        key=lambda argument: (argument.lineno, argument.col_offset),
    )


def call_requires_multiline(arguments: list[ast.expr | ast.keyword]) -> bool:
    if len(arguments) >= MULTILINE_CALL_MIN_ARGUMENTS:
        return True
    arguments_text = ", ".join(ast.unparse(argument) for argument in arguments)
    return len(arguments_text) >= MULTILINE_CALL_MIN_ARGUMENTS_LENGTH


def is_properly_exploded(
    node: ast.Call,
    arguments: list[ast.expr | ast.keyword],
    line_bytes: list[bytes],
) -> bool:
    """
    Tells whether every argument of a call sits on its own line and ends with a trailing comma.

    :param node: The call being checked.
    :param arguments: The call's arguments in source order.
    :param line_bytes: The file's lines encoded as UTF-8.
    :return: True when the call is laid out one argument per line with a trailing comma.
    """
    previous_end_line = node.func.end_lineno
    for argument in arguments:
        if previous_end_line is None or argument.lineno <= previous_end_line:
            return False
        previous_end_line = argument.end_lineno
    last_argument = arguments[-1]
    if last_argument.end_lineno is None or last_argument.end_col_offset is None:
        return False
    if node.end_lineno is None or node.end_col_offset is None:
        return False
    closing_text = read_source_segment(
        line_bytes,
        (last_argument.end_lineno, last_argument.end_col_offset),
        (node.end_lineno, node.end_col_offset),
    )
    return "," in closing_text


def check_multiline_calls(
    path: Path,
    tree: ast.Module,
    line_bytes: list[bytes],
    parents: dict[ast.AST, ast.AST],
) -> list[Violation]:
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or is_inside_f_string(node, parents):
            continue
        arguments = get_call_arguments(node)
        if len(arguments) == 0:
            continue
        if len(node.args) == 1 and len(node.keywords) == 0 and isinstance(node.args[0], ast.GeneratorExp):
            continue
        if not call_requires_multiline(arguments):
            continue
        if node.lineno == node.end_lineno and is_argument_of_single_line_call(node, parents):
            continue
        if is_properly_exploded(
            node,
            arguments,
            line_bytes,
        ):
            continue
        violation = Violation(
            path,
            node.lineno,
            "PY-24",
            f"'{get_called_name(node) or 'call'}(...)' has 3+ arguments or 50+ characters of arguments: "
            "put each argument on its own line and add a trailing comma.",
        )
        violations.append(violation)
    return violations


def check_get_prefix(path: Path, tree: ast.Module) -> list[Violation]:
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, FUNCTION_NODE_TYPES) or not node.name.startswith(GET_PREFIX):
            continue
        violation = Violation(
            path,
            node.lineno,
            "PY-62",
            f"New functions never start with 'get_': name it '{node.name.removeprefix(GET_PREFIX)}'. "
            "Keep the name only if the function already existed with it.",
        )
        violations.append(violation)
    return violations


def is_boolean_operand(node: ast.expr) -> bool:
    """
    Tells whether an `or` operand is clearly a boolean, so the `or` is a condition and not a default.

    :param node: One operand of the `or`.
    :return: True for comparisons, `not`, bool constants, predicate calls and `is_`/`has_` names.
    """
    if isinstance(node, (ast.Compare, ast.BoolOp)):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return True
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return True
    operand_name = get_called_name(node)
    if operand_name is None:
        return False
    if isinstance(node, ast.Call) and operand_name in BOOLEAN_CALL_NAMES:
        return True
    return operand_name.startswith(BOOLEAN_NAME_PREFIXES)


def is_condition_position(node: ast.BoolOp, parents: dict[ast.AST, ast.AST]) -> bool:
    parent = parents.get(node)
    if isinstance(parent, CONDITION_PARENT_TYPES):
        return True
    return isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not)


def check_or_defaults(
    path: Path,
    tree: ast.Module,
    parents: dict[ast.AST, ast.AST],
) -> list[Violation]:
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BoolOp) or not isinstance(node.op, ast.Or):
            continue
        if is_condition_position(node, parents):
            continue
        if any(is_boolean_operand(operand) for operand in node.values):
            continue
        violation = Violation(
            path,
            node.lineno,
            "PY-56",
            "Never pick a value with 'or' (it swallows 0, '' and []): write "
            "'value if value is not None else default' or 'if value is None: value = default'.",
        )
        violations.append(violation)
    return violations


def check_python_file(path: Path) -> list[Violation]:
    """
    Runs every convention check on one Python file.

    :param path: The file to check.
    :return: All violations found, sorted by line.
    """
    raw_source = path.read_bytes()
    source = raw_source.decode("utf-8-sig")
    if source.strip() == "":
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as syntax_error:
        violation = Violation(
            path,
            syntax_error.lineno or 1,
            "PY-SYNTAX",
            f"Syntax error: {syntax_error.msg}",
        )
        return [violation]
    lines = source.splitlines()
    line_bytes = [line.encode("utf-8") for line in lines]
    parents = build_parent_map(tree)
    violations = check_encoding(path, raw_source)
    violations += check_none_returns(path, tree)
    violations += check_docstrings(
        path,
        tree,
        lines,
    )
    violations += check_dunder_all(path, tree)
    violations += check_exceptions(path, tree)
    violations += check_get_prefix(path, tree)
    violations += check_or_defaults(
        path,
        tree,
        parents,
    )
    if not is_test_file(path):
        violations += check_parameter_annotations(
            path,
            tree,
            parents,
        )
        violations += check_module_header(path, tree)
        violations += check_banners(
            path,
            tree,
            lines,
        )
        violations += check_multiline_calls(
            path,
            tree,
            line_bytes,
            parents,
        )
    return sorted(violations, key=lambda violation: violation.line)


def collect_python_files(raw_paths: list[str]) -> list[Path]:
    python_files: list[Path] = []
    for raw_path in raw_paths:
        path = Path(raw_path)
        if path.is_dir():
            python_files.extend(sorted(path.rglob("*.py")))
        elif path.suffix == ".py" and path.is_file():
            python_files.append(path)
    return python_files


def write_utf8(text: str):
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check Python files against the house conventions.",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Python files or directories to check.",
    )
    parsed_arguments = parser.parse_args()
    violations: list[Violation] = []
    for python_file in collect_python_files(parsed_arguments.paths):
        violations += check_python_file(python_file)
    if len(violations) == 0:
        return 0
    for violation in violations:
        write_utf8(violation.format_for_output() + "\n")
    write_utf8(f"{len(violations)} convention violation(s).\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
