# ABOUTME: Family-level drift check — the shell lexer and promote parser duplicated across Bash guards.
# ABOUTME: Compares the duplicated members of every canonical source and its deployed byte-copy.

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# The guards that carry the DUPLICATE lexer block, each held together by a
# prose comment and nothing else. This test is the "nothing else".
_HOOKS = (
    "check_destructive_command.py",
    "guard_main_worktree.py",
    "guard_promote_cadence.py",
    "guard_promote_ci_red.py",
    "guard_shared_venv.py",
    "guard_trunk_pull.py",
)

# The promote guards, which also carry the DUPLICATE promote-parser block.
_PARSER_HOOKS = (
    "guard_promote_cadence.py",
    "guard_promote_ci_red.py",
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

# The members of the duplicated promote parser, ``_PR_CREATE_VALUE_FLAGS`` to
# ``find_promote``, in declaration order. Each guard's ``PROMOTE_REPOS`` and
# ``OVERRIDE_VAR`` differ on purpose and sit outside the block.
_PARSER_MEMBERS = (
    "_PR_CREATE_VALUE_FLAGS",
    "_API_VALUE_FLAGS",
    "_API_FIELD_FLAGS",
    "_PULLS_ENDPOINT",
    "_options",
    "_last",
    "_assigned",
    "_slug",
    "_branch",
    "_next_cwd",
    "_WRAPPER_VALUE_FLAGS",
    "_ENV_VALUE_FLAGS",
    "_SHELLS",
    "_SHELL_VALUE_FLAGS",
    "_skip_flags",
    "_after_env",
    "_unwrap",
    "_shell_script",
    "_PROMOTE_BRANCH",
    "_carries_staging",
    "_is_promote",
    "_defaults_to_trunk",
    "Promote",
    "_Context",
    "_pr_create_promote",
    "_fill_placeholders",
    "_api_repo",
    "_api_promote",
    "_gh_promote",
    "_promote_in",
    "find_promote",
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
    return _paths(_HOOKS)


def _parser_paths() -> list[Path]:
    """Every file carrying the promote parser — each canonical source and its deploy."""
    return _paths(_PARSER_HOOKS)


def _paths(hooks: tuple[str, ...]) -> list[Path]:
    root = _repo_root()
    paths = []
    for name in hooks:
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
        if isinstance(node, ast.FunctionDef | ast.ClassDef) and node.name == name:
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


def parser_signature(source: str) -> str:
    """The duplicated promote parser's code, docstrings included.

    The parser is held byte-identical, prose and all, so only comments — which
    never reach the AST — may differ. A missing member raises
    :class:`LexerMemberMissing`, as for the lexer.
    """
    tree = ast.parse(source)
    return "\n".join(ast.dump(_member(tree, name)) for name in _PARSER_MEMBERS)


def _signatures(paths: list[Path]) -> dict[Path, str]:
    return {path: lexer_signature(path.read_text(encoding="utf-8")) for path in paths}


def _parser_signatures(paths: list[Path]) -> dict[Path, str]:
    return {path: parser_signature(path.read_text(encoding="utf-8")) for path in paths}


def test_every_guard_carrying_the_block_is_present():
    """A missing file must fail here, not silently shrink the comparison set."""
    paths = _lexer_paths()
    assert len(paths) == 2 * len(_HOOKS)
    missing = [str(path) for path in paths if not path.is_file()]
    assert not missing, f"guards missing from the family: {missing}"


def test_the_duplicated_lexer_has_not_drifted():
    """The whole point: six hooks, twelve files, one lexer."""
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


def test_every_guard_carrying_the_parser_is_present():
    paths = _parser_paths()
    assert len(paths) == 2 * len(_PARSER_HOOKS)
    missing = [str(path) for path in paths if not path.is_file()]
    assert not missing, f"promote guards missing: {missing}"


def test_the_duplicated_promote_parser_has_not_drifted():
    """Two promote guards, four files, one parser."""
    signatures = _parser_signatures(_parser_paths())
    assert len(set(signatures.values())) == 1, (
        "the DUPLICATE promote parser has drifted between: "
        + ", ".join(sorted(str(path) for path in signatures))
    )


@pytest.mark.parametrize(
    ("anchor", "edit"),
    [
        # Behaviour: the base check of gh pr create.
        ("if base is not None and _branch(base) != TRUNK:", "if base is not None and False:"),
        # A decorator: Promote stops being a frozen dataclass.
        ("@dataclass(frozen=True)\nclass Promote:", "@dataclass\nclass Promote:"),
        # Prose: the parser is held byte-identical, docstrings included.
        (
            '"""The value of the last of ``names`` given — the one gh would use."""',
            '"""Reworded."""',
        ),
    ],
)
def test_the_parser_check_detects_one_edited_copy(tmp_path, anchor, edit):
    """The negative fixture — edit one parser copy and watch the comparison stop agreeing."""
    paths = _parser_paths()
    original = paths[-1].read_text(encoding="utf-8")
    mutated = original.replace(anchor, edit, 1)
    assert mutated != original, "the mutation anchor is gone — the fixture is inert"
    mutant = tmp_path / "guard_drifted.py"
    mutant.write_text(mutated, encoding="utf-8")

    signatures = _parser_signatures([*paths, mutant])
    assert len(set(signatures.values())) == 2
    assert signatures[mutant] != signatures[paths[0]]


def test_the_repo_table_is_outside_the_parser():
    """The two guards differ in their repos on purpose; that must not read as drift."""
    cadence, ci_red = (path.read_text(encoding="utf-8") for path in _parser_paths()[::2])
    assert "PROMOTE_REPOS = {" in cadence and "PROMOTE_REPOS = {" in ci_red
    assert parser_signature(cadence) == parser_signature(ci_red)


def test_a_renamed_parser_member_is_reported_not_skipped():
    source = _parser_paths()[0].read_text(encoding="utf-8")
    renamed = source.replace("def _defaults_to_trunk(", "def _defaults_renamed(", 1)
    with pytest.raises(LexerMemberMissing):
        parser_signature(renamed)
