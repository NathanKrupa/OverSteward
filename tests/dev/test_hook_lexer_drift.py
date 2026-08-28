# ABOUTME: Family-level drift check — the shell lexer duplicated across four Bash guards must not diverge.
# ABOUTME: Compares the lexer members of every canonical source and its deployed byte-copy.

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# The four guards that carry the DUPLICATE lexer block, each held together by a
# prose comment and nothing else. This test is the "nothing else".
_HOOKS = (
    "check_destructive_command.py",
    "guard_main_worktree.py",
    "guard_shared_venv.py",
    "guard_trunk_pull.py",
)

# The members of the duplicated block, in the order the guards declare them.
_LEXER_MEMBERS = (
    "_SEPARATORS",
    "_BACKTICK",
    "_ASSIGNMENT",
    "_lex",
    "_token_runs",
    "_simple_commands",
    "_split_assignments",
    "_invocations",
)


class LexerMemberMissing(LookupError):
    """A guard does not declare a member of the duplicated lexer block."""


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "shared" / "scripts" / "dev").is_dir():
            return parent
    raise FileNotFoundError(f"could not locate the repo root above {__file__}")


def _lexer_paths() -> list[Path]:
    """Every file carrying the block — each canonical source and its deploy."""
    root = _repo_root()
    paths = []
    for name in _HOOKS:
        paths.append(root / "shared" / "scripts" / "dev" / name)
        paths.append(root / ".claude" / "hooks" / name)
    return paths


def _strip_docstrings(node: ast.AST) -> ast.AST:
    """``node`` with every function's leading docstring removed.

    Each guard illustrates the lexer with an example from its own domain, so
    the prose deliberately differs while the code must not. Comparing the code
    means comparing what runs — comments never reach the AST, and docstrings
    are dropped here for the same reason.
    """
    for child in ast.walk(node):
        if not isinstance(child, ast.FunctionDef):
            continue
        first = child.body[0] if child.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            child.body = child.body[1:]
    return node


def _member(tree: ast.Module, name: str) -> ast.AST:
    """The top-level definition of ``name``, or raise."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return node
    raise LexerMemberMissing(name)


def lexer_signature(source: str) -> str:
    """The duplicated lexer's code, normalized so only behaviour is compared.

    Raises :class:`LexerMemberMissing` when a member is absent: a guard that
    renamed or dropped part of the block has drifted in the way hardest to
    notice, and "could not look" must never read the same as "found nothing".
    """
    tree = ast.parse(source)
    return "\n".join(
        ast.dump(_strip_docstrings(_member(tree, name))) for name in _LEXER_MEMBERS
    )


def _signatures(paths: list[Path]) -> dict[Path, str]:
    return {path: lexer_signature(path.read_text(encoding="utf-8")) for path in paths}


def test_every_guard_carrying_the_block_is_present():
    """A missing file must fail here, not silently shrink the comparison set."""
    paths = _lexer_paths()
    assert len(paths) == 2 * len(_HOOKS)
    missing = [str(path) for path in paths if not path.is_file()]
    assert not missing, f"guards missing from the family: {missing}"


def test_the_duplicated_lexer_has_not_drifted():
    """The whole point: four hooks, eight files, one lexer."""
    signatures = _signatures(_lexer_paths())
    distinct = set(signatures.values())
    assert len(distinct) == 1, (
        "the DUPLICATE lexer block has drifted across the guard family; "
        "signatures differ between: "
        + ", ".join(sorted(str(path) for path in signatures))
    )


def test_the_check_detects_a_mutated_copy(tmp_path):
    """The negative fixture — mutate one copy and watch the check go red.

    A drift check that has never been seen fail is decoration. This changes
    one behavioural line of the lexer in a copy of a real guard and asserts the
    comparison stops agreeing.
    """
    paths = _lexer_paths()
    original = paths[0].read_text(encoding="utf-8")
    mutated = original.replace(
        "lexer.whitespace_split = True", "lexer.whitespace_split = False", 1
    )
    assert mutated != original, "the mutation anchor is gone — the fixture is inert"
    mutant = tmp_path / "guard_drifted.py"
    mutant.write_text(mutated, encoding="utf-8")

    signatures = _signatures([*paths, mutant])
    assert len(set(signatures.values())) == 2
    assert signatures[mutant] != signatures[paths[0]]


def test_a_prose_only_difference_is_not_drift(tmp_path):
    """Per-guard examples in comments and docstrings are deliberate, not drift."""
    original = _lexer_paths()[0].read_text(encoding="utf-8")
    reworded = original.replace(
        '"""``text`` as shell tokens, or None if a quote is left open."""',
        '"""Reworded prose that changes no behaviour."""',
        1,
    )
    assert reworded != original
    assert lexer_signature(reworded) == lexer_signature(original)


def test_a_renamed_member_is_reported_not_skipped():
    """A guard that renamed part of the block must raise, never quietly pass."""
    source = _lexer_paths()[0].read_text(encoding="utf-8")
    without_lex = source.replace("def _lex(", "def _lex_renamed(", 1)
    with pytest.raises(LexerMemberMissing):
        lexer_signature(without_lex)
