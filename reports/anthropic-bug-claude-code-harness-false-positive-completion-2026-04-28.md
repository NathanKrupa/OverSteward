ABOUTME: Bug report draft for Anthropic — Claude Code harness terminates subagent after tool result without waiting for next assistant turn.
ABOUTME: Filed 2026-04-28 by Nathan Krupa from session 3e546344. Submit to claude-code GitHub issues at https://github.com/anthropics/claude-code/issues.

# Claude Code: harness terminates subagent immediately after tool result, without awaiting next assistant turn

**Severity:** High — silently drops in-progress agent work. The harness reports `status: completed` but the agent never finished. Visible in production: 4 consecutive `local_agent` task failures on a single Claude Code session 2026-04-28, all with the same JSONL pattern. Each lost 13-90 minutes of agent work.

**Environment:**

- Claude Code: latest (whatever shipped 2026-04-26 / 2026-04-28)
- Platform: Windows 11 Home 10.0.26200
- Shell: bash (Git Bash)
- Subagent type: custom (`aigranthelper-dev`, `model: opus`, tools: Bash/Read/Edit/Write/Grep/Glob)
- Model resolved: claude-opus-4-7
- Spawn mechanism: `Task` tool with `subagent_type: aigranthelper-dev`, `run_in_background: true`

**Reproduction:**

We don't have a reliable trigger — it appears intermittently on long-running architectural-refactor dispatches that touch ~10+ files and reach ~135+ turns / ~128k cache_read. Tool calls that complete very quickly (~40 ms tool_use → tool_result delivery) seem to correlate with the failure; tool calls with longer runtimes (~9 s for a heavier Edit/Write) succeed.

Across 4 failures observed in one session:

| Session | Issue | Wall-clock | Last few turns |
|---|---|---|---|
| `agent-ad3a1cac6ce4697b7` | aigranthelper #351 v1 | ~13 min | `tool_use` → `tool_result` (35 ms gap) → file ends |
| `agent-ab01c697a3e6e80e7` | aigranthelper #351 v2 | ~16 min | `tool_use` → `tool_result` (43 ms gap) → file ends |
| `agent-a4f50cde2be6af44e` | aigranthelper #306 | ~13 min | `tool_use` → `tool_result` (1.0 s gap) → file ends |
| `agent-a93518662f3941cbf` | aigranthelper #327 | ~55 min | (different — actual API stream timeout error) |

Successful dispatches in the same session show the same `tool_use` → `tool_result` pattern, but with longer gaps (3-9 s) AND a follow-up assistant turn:

| Session | Last few turns |
|---|---|
| `agent-a8f3bd9b9226be1b3` (succeeded, #318) | `tool_use` (02:45:43) → `tool_result` (02:45:52, 9 s gap) → `assistant / end_turn` (02:46:27) |

**Smoking-gun pattern (failed dispatch JSONL tail, illustrative):**

```
{"type":"assistant", "stop_reason":"tool_use", "timestamp":"2026-04-28T13:44:31.879Z", ...}
{"type":"user", "timestamp":"2026-04-28T13:44:31.922Z", "message":{"content":[{"type":"tool_result", ...}]}}
[FILE ENDS — no further turns]
```

The `user` turn is the harness delivering the tool result back to the model. The model's next turn (which should follow with `stop_reason` ∈ {`end_turn`, `tool_use`, `max_tokens`, `stop_sequence`}) never arrives. The harness sends `task-notification` with `status: completed` to the parent task, ~1 second after the tool result is delivered.

The parent's task-notification result is whatever text the agent had emitted MOST RECENTLY before the tool call — i.e., a mid-narrative fragment like:

- `"Now add regression tests:"`
- `"I'll create a single file for the new dataclass construction tests:"`
- `"Approach: introduce a private \`_NormalizedGrant\` dataclass that..."`
- `"All pre-existing diagnostics. Continuing."`

These are clearly NOT terminal — the agent was about to take its next action.

**Hypothesis:**

A race condition in the harness state machine: when a tool result is delivered very quickly after the corresponding tool_use, the harness can transition to "agent done" before the model's response stream is fully attached. Specifically, my guess is that one of:

1. The harness fires the next API request to the model with the tool result, but doesn't await its response stream — instead treating "tool result successfully delivered to model" as terminal.
2. The harness DOES await the response, but a watchdog/timeout fires inappropriately when the round-trip is too fast.
3. There's a bug in the Stop-condition logic where `stop_reason: tool_use` is being treated as terminal in some code path that should require `stop_reason ∈ {end_turn, max_tokens, stop_sequence}`.

**Suggested fix:**

The harness should not mark a subagent as `completed` until the most recent assistant turn has `stop_reason ∈ {end_turn, max_tokens, stop_sequence}`. A `stop_reason: tool_use` last turn means the model is mid-conversation and the harness still needs to handle the next round. If the API request that should follow the tool result fails, the harness should report `failed` (or `errored`), not `completed`.

**Workarounds (consumer side):**

1. Heartbeat-commit: agent pushes its branch periodically so partial work survives termination.
2. Dispatcher-side verification: the parent task verifies a structured final-report was actually emitted before trusting the `completed` status; if missing, treats it as a special `HARNESS_DROPPED` state and re-dispatches from the heartbeat-pushed branch.

Both have been added to our local dispatch playbook (v1.8) but they are workarounds, not a fix.

**Files / pointers:**

JSONL transcripts available on request (paths under `~/.claude/projects/c--Users-natha-OneDrive-Tech-Python-Oversteward/3e546344-ca32-42d4-bae2-32c3be5a9344/subagents/`). Will not embed here in case they contain anything sensitive. Happy to share with Anthropic privately.

**Reporter:** Nathan Krupa (`nathankrupa@gmail.com`)
