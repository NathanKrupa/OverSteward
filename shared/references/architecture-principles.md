# Architecture Principles — Portable Reference
# @import this from any project's CLAUDE.md to carry these forward.

## Three-Layer Model

Every codebase has three layers. Arrows point inward only.

```
OUTER  →  MIDDLE  →  INNER
```

| Layer | Contains | Responsibility | Size |
|-------|----------|---------------|------|
| **OUTER** | Scripts, CLI, views, API endpoints, skills | Parse input → call service → format output | 3-10 lines of real logic |
| **MIDDLE** | Services, engines, pipelines | Business rules, orchestration, decisions | The real work lives here |
| **INNER** | Connectors, stores, models, clients | Talks to ONE external system each | No business logic |

## The Service Test

Can you describe what this code does without mentioning HTTP, SQL, `print()`, or `argparse`? If yes, it's a service. If no, business logic is tangled with infrastructure.

## Decision Rules

Before writing code, answer: **"Which layer does this belong to?"**

### Import Direction
Outer imports Middle. Middle imports Inner. **NEVER reverse.**
A connector must never import a service. A service must never import a script.

### Thin Entry Points
A script with >20 lines of non-CLI logic is a fat script. Extract the logic to a service in the middle layer. The script becomes: parse args → call service → print result.

### Duplication Signal
The same logic appearing in 2+ files means a service is missing. Extract to a shared service immediately. Do not copy-paste between scripts.

### Config Injection
Classes take dependencies as `__init__` parameters. Only factory functions or composition roots read `os.getenv()`. A class that reads environment variables internally cannot be tested without mocking the environment.

### One Connector, One System
A connector talks to WordPress OR Kit OR Neon OR the filesystem. Never two. If a connector coordinates multiple systems, it's a service pretending to be a connector.

### Dependency Seams

Code that crosses a boundary to an external or global system — `subprocess`, HTTP clients, filesystem, `datetime.now`, `time.sleep`, `random`, `os.environ` reads, database connections — must take the seam as a **parameter**, not read it as a module global.

Production code passes the real implementation. Tests pass a stub. The seam appears in the function signature, which means callers know what the function depends on and tests can substitute without mutating global state.

**Signal that a seam is missing:** a test that writes `monkeypatch.setattr("module.attr", fake)` (or similar patching of a module global) is reporting that the code under test has a hidden dependency. The fix is to expose the seam in the signature — not to write a more elaborate patch.

```python
# LEAK: subprocess.run is a module global reached via import. Tests can only
# hit it by patching, and the call site doesn't document the dependency.
def run_check(root):
    return subprocess.run(["tool", str(root)], capture_output=True)

# FIX: the runner is a parameter with a sensible default. Tests pass a stub
# directly; readers see the dependency in the signature.
def run_check(root, *, runner=subprocess.run):
    return runner(["tool", str(root)], capture_output=True)
```

**Exception:** truly third-party code where injection would bloat every call site AND no realistic test substitute is needed. Rare. Err toward injection.

### Connector vs. Service Boundary
- Connector answers: **"How do I talk to X?"** (HTTP verbs, SQL syntax, auth headers, retries)
- Service answers: **"What should happen?"** (business rules, eligibility, scoring, orchestration)

If a connector makes business decisions (which records are eligible, what score means "good"), that logic leaked from the service layer.

## Extraction Pattern

When you find a fat script:

```
BEFORE (fat script):
  scripts/domain/do_thing.py
  ├── business_logic_a()    ← trapped
  ├── business_logic_b()    ← trapped
  └── main()                ← CLI + logic tangled

AFTER (thin entry point + service):
  src/package/domain/thing.py    ← business_logic_a(), business_logic_b()
  scripts/domain/do_thing.py     ← parse args → call service → print
```

## Vocabulary Quick Reference

| Term | Meaning |
|------|---------|
| **Service** | Middle-layer code implementing business rules via connectors |
| **Connector** | Inner-layer code translating between your domain and one external system |
| **Fat script** | Script with business logic trapped inside, unreachable by other callers |
| **Thin entry point** | Script reduced to parse → call → format |
| **Import direction** | Dependencies flow inward (outer → middle → inner), never outward |
| **Config injection** | Passing config into a class rather than having it read env vars |
| **Duplication signal** | Same logic in 2+ files, indicating a missing shared service |
| **Leak** | Business logic that escaped from its proper layer into another |
| **Seam** | A boundary to an external or global system, exposed as a parameter so callers (tests included) can substitute implementations without patching module globals |

## PM Evaluation Questions

When reviewing any script or feature:
1. **"Is there business logic in this script?"** — If the script makes decisions beyond parsing input and formatting output, that logic should be a service.
2. **"Could a second caller use this logic?"** — If another script, skill, or test would want the same rules, it's a service.
3. **"Is the same rule defined in more than one place?"** — Duplication is the loudest signal that a service is missing.

## When Building New Features

1. Identify the layer for each piece of code before writing it
2. Start with the service (middle layer) — that's where the real logic lives
3. Write the connector only if you need to talk to a new external system
4. Write the entry point last — it should be trivial
5. If you catch yourself adding business logic to a script or connector, stop and move it

## The Boy-Scout Rule

**Leave every file you touch substantially better than you found it.**

Per-file monotonic-down, not aggregate. A file modified in a PR ends with
fewer findings (lint, type, smell, dead code, stale comment, weak name) than
its version on main. Files at zero stay at zero.

Aggregate ratchets bound total drift but let debt accumulate inside hot
files. Per-file enforcement keeps the trend downward where work is
happening. Cold files keep their findings — nobody touches them, so they
don't matter to the next reader.

**Exemptions:** new files (no baseline), generated files (migrations,
`*_generated.py`, vendored code — cleanup doesn't survive regeneration).

**When you genuinely can't improve a file you had to touch** (one-character
bugfix, every other finding is structural): land a separate cleanup PR for
that file first, then rebase. Do not raise thresholds. Do not `# noqa` to
dodge.

**Three kinds of finding — fix, justify, or defer; never chase the count.**
The ratchet's purpose is *less real defect surface*, not a smaller number.
When a touched file's remaining findings can't be honestly reduced, classify
each before acting:

1. **Real defect** (silent `except`, dead code, weak name, genuine smell) —
   *fix it in scope.* The normal case; this is what the rule is for.
2. **Tool false-positive, already correctly suppressed** — a `# noqa` over a
   finding the tool is *demonstrably wrong about* is a legitimate suppression,
   not a dodge. Do **not** refactor correct, working code to drive a count
   that is already zero. Justify in place and fix the rule **upstream at the
   canonical tool** (e.g. a gaudi issue); the upstream fix clears the
   suppression fleet-wide at zero blast radius.
3. **Desirable but orthogonal modernization** (e.g. a framework-idiom
   migration) — worthwhile, but it is **its own scoped work**, never collateral
   forced by an unrelated lint chore. Spin it out; don't let ratchet pressure
   drag a risky refactor into a change that didn't need it.

This refines "don't `# noqa` to dodge": the ban is on hiding a *real* finding.
Suppressing one the tool misjudges is correct — the honest move is to fix the
tool, not the code it misreads.

**Where it's enforced by tooling:** projects with `check_boy_scout.py` gate
this in CI and pre-push. Elsewhere, apply by judgment — scan for one or
more cleanups (stale comment, weak name, dead branch, lint finding) and
include them in the same commit.
