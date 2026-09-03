---
name: skill-miner
description: "Mine session transcripts for Bash sequences the estate keeps re-deriving and draft a SKILL.md per cluster into a review directory. Deterministic, zero-LLM, never installs a skill. Invoke when Nathan asks what should become a skill, says \"skill miner\" / \"/skill-miner\", or after a run of sessions that felt repetitive."
---

# /skill-miner — find the procedures nobody wrote down

Claude Code has no tool that notices repeated work; the documented path is to
notice it by hand. This pass does the noticing. It walks every session
transcript, keeps each Bash call, reduces it to a signature (program plus
subcommand, nothing else), and counts how many **distinct sessions** ran each
contiguous sequence of signatures. A sequence that recurs across enough
sessions is a procedure the estate keeps re-deriving.

```bash
.venv/bin/python scripts/skill_miner.py --dry-run                 # rank, write nothing
.venv/bin/python scripts/skill_miner.py --min-sessions 4          # drafts → reports/skill-drafts/<today>/
.venv/bin/python scripts/skill_miner.py --repo grantspider --since-days 30
```

Exit `0` is a measurement; exit `1` means transcripts were found but none could
be read (the count is on stderr); exit `2` means no transcripts were found to
look at. Never collapse the three.

## Reading the output

- `INDEX.md` ranks candidates by session support, then length. Each row names
  its steps and any existing skill that already prescribes every step.
- **"already in: X"** is a different finding from "no skill exists": the
  sequence is being re-derived instead of invoked, so the fix is X's trigger
  line, not a new skill.
- Each `<slug>/SKILL.md` is a **draft**: provenance, then one step per
  signature with the most common concrete command seen. Rewrite the
  description to say *when* to invoke it, delete incidental steps, then move
  it into `.claude/skills/` (or `~/.claude/skills/`) yourself. The miner never
  installs anything.

## What it deliberately ignores

Inspection commands (`grep`, `sed`, `cat`, `ls`), shell plumbing, inline
`python -c` snippets, and heredoc bodies are not steps — a skill is what you
do, not what you looked at first. Consecutive repeats of one signature collapse,
so a poll loop is one step. Wrappers (`timeout`, `nohup`) sign as the command
they wrap.
