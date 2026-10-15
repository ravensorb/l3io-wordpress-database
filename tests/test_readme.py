"""The README's examples use only what exists.

The README is the first thing a user runs. Its library examples import only
names the package exports, and every command line it shows parses.
"""

from __future__ import annotations

import ast
import re
import shlex
from pathlib import Path

import pytest

import l3io.wp.database as database
from l3io.wp.database.cli import build_parser

README = Path(__file__).resolve().parent.parent / "README.md"
_BLOCK = re.compile(r"^```(\w+)\n(.*?)^```", re.MULTILINE | re.DOTALL)


def blocks(text: str, language: str) -> list[str]:
    return [body for lang, body in _BLOCK.findall(text) if lang == language]


def imported_names(source: str) -> set[str]:
    return {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module == "l3io.wp.database"
        for alias in node.names
    }


def commands(source: str) -> list[list[str]]:
    joined = source.replace("\\\n", " ")
    return [
        shlex.split(line)[1:]
        for line in joined.splitlines()
        if line.strip().startswith("l3io-wordpress-database ")
    ]


def test_every_python_example_imports_only_exported_names() -> None:
    sources = blocks(README.read_text(encoding="utf-8"), "python")
    assert sources, "README has no Python example -- this guard is vacuous"
    names = set().union(*(imported_names(s) for s in sources))
    assert names, "no README example imports from l3io.wp.database"
    assert not sorted(names - set(database.__all__))


def test_every_command_line_example_parses() -> None:
    found = [c for s in blocks(README.read_text(encoding="utf-8"), "shell") for c in commands(s)]
    assert found, "README shows no command line -- this guard is vacuous"
    parser = build_parser()
    for argv in found:
        try:
            parser.parse_args(argv)
        except SystemExit:
            pytest.fail(f"README command does not parse: {shlex.join(argv)}")


def test_an_unexported_name_is_caught() -> None:
    assert imported_names("from l3io.wp.database import WpDatabase, Database\n") == {
        "WpDatabase",
        "Database",
    }
