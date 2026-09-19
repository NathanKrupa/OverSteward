# ABOUTME: Tests for how the board picks its repositories out of registry.yaml.
# ABOUTME: Dispatch targets only, named by their GitHub owner/name, not their registry id.

from __future__ import annotations

import pytest

from oversteward.board.config import RepoRef, repos_from_registry


def test_only_dispatch_targets_are_board_repos():
    registry = {
        "contexts": [
            {
                "id": "oversteward",
                "repo": "https://github.com/NathanKrupa/OverSteward.git",
                "dispatch_target": True,
            },
            {"id": "billions", "repo": "https://github.com/NathanKrupa/billions.git"},
            {
                "id": "fiscus",
                "repo": "https://github.com/NathanKrupa/fiscus.git",
                "dispatch_target": False,
            },
        ]
    }

    assert repos_from_registry(registry) == [
        RepoRef(id="oversteward", full_name="NathanKrupa/OverSteward"),
    ]


def test_the_gh_name_comes_from_the_repo_url_not_the_registry_id():
    registry = {
        "contexts": [
            {
                "id": "oversteward",
                "repo": "https://github.com/NathanKrupa/OverSteward",
                "dispatch_target": True,
            },
        ]
    }

    (ref,) = repos_from_registry(registry)

    assert ref.full_name == "NathanKrupa/OverSteward"
    assert ref.name == "OverSteward"


def test_a_dispatch_target_without_a_github_url_is_a_misconfiguration():
    registry = {
        "contexts": [{"id": "x", "repo": "git@bitbucket.org:o/x.git", "dispatch_target": True}]
    }

    with pytest.raises(ValueError, match="x"):
        repos_from_registry(registry)


def test_an_empty_registry_yields_no_repos():
    assert repos_from_registry({}) == []
