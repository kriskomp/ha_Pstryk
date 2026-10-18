"""Static checks of the integration's code, independent of the Python version.

Python 3.14 (Home Assistant) warns about `return` in `finally` (PEP 765) where
3.13 is silent; leftovers of an edit can also leave unreachable code or a
method defined twice. These checks catch all three with the ast module.
"""
import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "custom_components" / "pstryk"
FILES = sorted(PKG.glob("*.py"))


def _tree(path):
    return ast.parse(path.read_text(), filename=str(path))


class _FinallyExit(ast.NodeVisitor):
    """return/break/continue that leaves a `finally` block (nested functions and loops excepted)."""

    def __init__(self):
        self.found = []

    def visit_Try(self, node):
        for stmt in node.finalbody:
            self._scan(stmt, in_loop=False)
        self.generic_visit(node)

    visit_TryStar = visit_Try

    def _scan(self, node, in_loop):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            return
        if isinstance(node, ast.Return) or (isinstance(node, (ast.Break, ast.Continue)) and not in_loop):
            self.found.append(node.lineno)
        loop = isinstance(node, (ast.For, ast.AsyncFor, ast.While))
        for child in ast.iter_child_nodes(node):
            self._scan(child, in_loop or loop)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_exit_from_finally(path):
    visitor = _FinallyExit()
    visitor.visit(_tree(path))
    assert visitor.found == [], f"{path.name}: return/break/continue in finally at lines {visitor.found}"


def _bodies(tree):
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody", "handlers"):
            block = getattr(node, field, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                yield block


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_unreachable_code_after_return(path):
    unreachable = []
    for block in _bodies(_tree(path)):
        for i, stmt in enumerate(block[:-1]):
            if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                unreachable.append(block[i + 1].lineno)
    assert unreachable == [], f"{path.name}: unreachable code at lines {unreachable}"


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_function_defined_twice_in_one_scope(path):
    duplicates = []
    for node in ast.walk(_tree(path)):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        seen = {}
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                decorated = any(isinstance(d, ast.Attribute) and d.attr in ("setter", "deleter")
                                for d in stmt.decorator_list)
                if stmt.name in seen and not decorated:
                    duplicates.append((stmt.name, seen[stmt.name], stmt.lineno))
                seen.setdefault(stmt.name, stmt.lineno)
    assert duplicates == [], f"{path.name}: defined twice: {duplicates}"
