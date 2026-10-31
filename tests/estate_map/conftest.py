# ABOUTME: A minimal, valid estate map as a plain dict — each test mutates one field to make one guard red.
# ABOUTME: Kept small so a fixture's only defect is the one the test names.

from __future__ import annotations

import copy
from typing import Any

import pytest

REGISTRY_IDS = ("oversteward", "grantspider", "aigranthelper")

_BASE: dict[str, Any] = {
    "version": 1,
    "mission": {
        "north_star": "A+ grant-writing tools for the servants of the poor.",
        "products": [
            {"id": "os", "serves": "the estate", "repo": "oversteward"},
            {"id": "gs", "serves": "AG", "repo": "grantspider"},
            {"id": "ag", "serves": "grant seekers", "repo": "aigranthelper"},
        ],
    },
    "policy": {
        "digest_budget_bytes": 14000,
        "explicit_only": {"grantspider": ["src/grantspider/services"]},
        "coverage_floor": {
            "oversteward": {"orphans": 0, "overlaps": 0},
            "grantspider": None,
            "aigranthelper": None,
        },
    },
    "repos": [
        {"id": "oversteward", "purpose": "control plane", "stack": "Python"},
        {"id": "grantspider", "purpose": "data producer", "stack": "Python"},
        {"id": "aigranthelper", "purpose": "SaaS", "stack": "Django"},
    ],
    "capabilities": [
        {
            "id": "ag.research",
            "kind": "code",
            "purpose": "Funder research for grant seekers.",
            "status": "live",
            "invariants": ["I-1"],
            "current_shape": "stub",
            "target_shape": "hold",
        },
        {
            "id": "gs.website-resolution",
            "kind": "code",
            "purpose": "Finds each funder's website.",
            "status": "live",
            "serves": ["ag.research"],
            "claims": {"grantspider": ["src/grantspider/services/website_resolver.py"]},
            "liabilities": ["G1"],
            "current_shape": "one module",
            "target_shape": "hold",
        },
        {
            "id": "os.sow",
            "kind": "code",
            "purpose": "Deploys the dev family.",
            "status": "live",
            "claims": {"oversteward": ["src/oversteward/sow/", "src/oversteward/dev_family.py"]},
            "current_shape": "six modules",
            "target_shape": "fold the deploy into one verb",
        },
    ],
    "seams": [
        {
            "id": "S-1",
            "label": "grantspider → aigranthelper (data)",
            "producer": ["grantspider"],
            "consumer": ["aigranthelper"],
            "flows": "views",
            "cite": "`views.py`",
            "invariants": ["I-2"],
        }
    ],
    "invariants": [
        {"id": "I-1", "status": "live", "text": "a", "cite": "x", "capabilities": ["ag.research"]},
        {"id": "I-2", "status": "live", "text": "b", "cite": "y"},
        {"id": "I-3", "status": "retired", "text": "c", "cite": "z"},
    ],
    "liabilities": [
        {
            "id": "G1",
            "text": "drift",
            "owner": "aigranthelper",
            "tracking": "t",
            "capabilities": ["gs.website-resolution"],
        }
    ],
}


@pytest.fixture
def raw() -> dict[str, Any]:
    """A fresh deep copy of the valid base map, safe to mutate."""
    return copy.deepcopy(_BASE)
