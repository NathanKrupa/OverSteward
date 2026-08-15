ABOUTME: How the matchmaker's `applied_to_external_signal` field gets populated — three ingestion paths from real user behaviour to telemetry.
ABOUTME: Captures the load-bearing infrastructure that makes the gold signal real instead of aspirational.

# Gold-Signal Ingestion — Capture

**Companion to:** [matchmaker-instrumentation.md](matchmaker-instrumentation.md) §5.8 (`follow_up` step, `applied_to_external_signal` field).
**Status:** v0 — design proposal, no path live yet.
**Authoritative for:** the three ingestion paths that turn observed user actions into the `applied_to_external_signal` telemetry field — the only signal grounded in real fundraising work.

> The `applied_to_external_signal` field is the gold. Without an ingestion path that actually populates it, the entire feedback loop is missing its load-bearing signal — the analysis layer can count clicks and dismisses all day, but it cannot tell which matches led to real outcomes. Three ingestion paths are needed; each must be designed, instrumented, and shipped before the matchmaker's gold-signal queries (§6 Q2, Q3 in matchmaker-instrumentation) can answer their questions.

---

## §1 Why a separate document

`matchmaker-instrumentation.md` §5.8 names the field and its three valid enum values (`kit_email_clicked | export_downloaded | manual_self_report`). It does not describe **how** any of those values gets written. Each enum value is its own ingestion pipeline with its own trigger, its own source system, its own mapping logic, and its own failure modes. They share a destination (`pipeline_history.jsonl`) and a schema (the `follow_up` row), but nothing else.

This capture exists so the three pipelines are designed up front, not retrofit when the analysis-layer queries return empty.

---

## §2 Shared concerns (all three paths)

Before the per-path detail, the rules that apply universally.

### 2.1 Mapping back to `(run_id, match_id, user_id)`

Every gold-signal event must reconstruct the original `run_id` from the matchmaker run that surfaced the match. Without `run_id`, the event cannot be joined to the matchmaker telemetry rows that produced the match in the first place — and analysis-layer Q3 ("matched often but never applied to") becomes unanswerable.

Reconstruction strategies, in order of preference:

1. **Carry `run_id` in the link itself.** A signed URL parameter (`?gs_run=<run_id_token>&gs_match=<match_id_token>`). Token is a short HMAC over `(run_id, match_id, user_id, expiry)` so it is tamper-resistant and unforgeable. Used for Kit emails (§3) and export downloads (§4).
2. **Lookup by `(user_id, match_id, recency)`.** When the user explicitly self-reports, derive `run_id` as the most recent matchmaker run within 30 days that surfaced this match to this user. Used for manual self-report (§5).

### 2.2 Idempotency

Gold-signal events are inherently retry-prone: emails get clicked twice, the back button reloads downloads, the user reports the same application three times. The schema must deduplicate without losing distinct events.

Idempotency key: `(user_id_hash, match_id_hash, applied_to_external_signal, signal_payload_hash, day)`. Two clicks on the same day on the same email → one row. A click on Tuesday and another on Friday → two rows (the user re-engaged a week later; that is a distinct signal). The `signal_payload_hash` lets a re-export of the same match later count as a separate event.

Stored as a unique index on the JSONL ingestion staging table; duplicate inserts are dropped at the loader, not at the source.

### 2.3 What "missing" looks like

Each path has a "we know something happened but we cannot resolve `run_id`" failure mode. The pipeline must still record the event — in a separate stream — rather than drop it silently. Filed at `data/gold_signal_unresolved.jsonl` with the partial fields and the reason for non-resolution. Monthly review reconciles unresolved events back to runs where possible and tunes the reconciliation logic where not.

### 2.4 No PII in transit

Per matchmaker-instrumentation §4, telemetry never stores raw user ids, EINs, foundation names, or any free-text. The ingestion paths must hash on the boundary — at the webhook receiver (Kit), at the export endpoint (GHP), at the self-report API. **The signed URL token in §2.1 carries hashes, not raw ids.** A leaked token reveals nothing about who the user is or what they looked at.

---

## §3 Path A — `kit_email_clicked` (Kit alert email link click)

The Sphere I alert workflow ([DETERMINISTIC_AGENTS.md](../DETERMINISTIC_AGENTS.md) §4.4) emails the user a digest of new matches. The user clicks a match link. That click is the signal.

### 3.1 Trigger event

User clicks a link in a matchmaker alert email sent through Kit.

### 3.2 Source system

Kit (formerly ConvertKit). Connector lives in `wphelper` per the canonical-connector rule (I-9). Kit has two relevant surfaces:
- **Outbound:** Kit broadcasts and sequences send emails. We control the link content.
- **Inbound:** Kit fires webhooks on subscriber events (`subscriber.link_clicked`, etc.) when configured.

We control both surfaces, so the round trip is clean.

### 3.3 Mapping logic

1. Alert generation builds the email body with one HTML link per match. Each link's `href` is `https://granthelperpro.com/gs/click?t=<token>` where `<token>` is an HMAC-signed compact JSON: `{"v": 1, "r": "<run_id>", "m": "<match_id_hash>", "u": "<user_id_hash>", "exp": <unix_ts>, "src": "kit_email"}`.
2. Token expiry is 30 days from email send. Older clicks are recorded in `data/gold_signal_unresolved.jsonl` with reason `TOKEN_EXPIRED` and dropped from telemetry — a click 6 months later is a different kind of signal and is not worth fabricating join logic for.
3. User clicks the link. Their browser hits `granthelperpro.com/gs/click?t=<token>`.
4. The endpoint:
   a. Verifies the HMAC. Bad signature → log to unresolved with reason `BAD_SIGNATURE` and 302 to the canonical match URL (the user still gets where they wanted to go).
   b. Confirms `exp > now`. Expired → log to unresolved with reason `TOKEN_EXPIRED` and 302.
   c. Writes a `follow_up` row with `applied_to_external_signal: "kit_email_clicked"`, `match_id_hash` from the token, `user_id_hash` from the token, `run_id` from the token, `action: "click"`, `match_position: <from-token-payload>`, `time_to_action_ms: now - email_send_ts`.
   d. 302s the user to the canonical match page.

### 3.4 Idempotency

Per §2.2. Same token clicked twice on the same day → one row. Click on day 1 and day 4 → two rows (the user re-engaged).

### 3.5 Failure modes

| Failure | Detection | Recovery |
|---|---|---|
| Endpoint down at click time | Kit-side retries do not exist (link click is not webhook-delivered) | Click is lost. Mitigated by the secondary Kit webhook (§3.6). |
| Token forged or tampered | HMAC verification | Log to unresolved + 302 to a generic search page. User-visible: link doesn't take them where expected. Acceptable. |
| Match deleted between email send and click | Token still valid but match no longer exists | Log to unresolved with reason `MATCH_NOT_FOUND` + 302 to a generic search. |
| Kit-side email-content cache injects an altered link | Token-mismatch in click vs send log | Log to unresolved with reason `LINK_MISMATCH`; revisit Kit settings. |

### 3.6 Secondary signal — Kit webhook

In parallel with the redirect endpoint, configure Kit to fire a `subscriber.link_clicked` webhook to `granthelperpro.com/gs/kit-webhook`. The webhook payload includes the subscriber and the URL clicked.

Two signals (redirect + webhook) for one event is redundant by design — they catch each other's failures. The loader deduplicates by `(user_id_hash, match_id_hash, day, kit_email_clicked)` per §2.2. If the redirect fires and the webhook does not, both still produce one row. If the redirect fails (endpoint down) but the webhook fires, the webhook produces the row.

### 3.7 What missing looks like

`data/gold_signal_unresolved.jsonl` rows with reasons `TOKEN_EXPIRED`, `BAD_SIGNATURE`, `MATCH_NOT_FOUND`, `LINK_MISMATCH`. A monthly count of each is itself a feedback signal — if `TOKEN_EXPIRED` grows, alert cadence may be too slow; if `BAD_SIGNATURE` grows, someone is hand-crafting URLs (probably benign but worth a glance).

---

## §4 Path B — `export_downloaded` (in-app export of a match)

The GHP UI lets a user export a match — as a PDF brief, a CSV row, or copy-to-clipboard. The export is itself a strong intent signal: the user is preparing to do work on this match outside GHP.

### 4.1 Trigger event

User clicks an export button on a match's detail page in GHP.

### 4.2 Source system

The GHP Django app itself. No external connector. The export endpoint lives in `aigranthelper/apps/matchmaker/views.py` (when implemented).

### 4.3 Mapping logic

1. Match detail pages are reached via URL paths that include the run id and the match id (e.g. `/matches/<run_id>/<match_id_hash>/`). The export button is a form post or a link on that page; `run_id` and `match_id_hash` are present in the request context without needing a token.
2. Export endpoint:
   a. Authenticates the request against the GHP session.
   b. Verifies `(user_id, run_id, match_id_hash)` is a valid combination — i.e. the matchmaker actually surfaced this match to this user in this run. Bad triple → 404 + log to unresolved with reason `INVALID_TRIPLE`.
   c. Generates the export artifact (PDF / CSV / clipboard payload).
   d. Writes a `follow_up` row with `applied_to_external_signal: "export_downloaded"`, hashed user/match ids, the `run_id`, `action: "export"`, `match_position` from the original presentation row (looked up by `(run_id, match_id_hash)`), and `time_to_action_ms: now - presentation_ts` (also looked up).
   e. Returns the artifact.

### 4.4 Idempotency

Per §2.2. Same export within a day → one row. Re-export the next day → two rows.

The export artifact itself can be regenerated freely; only the telemetry row deduplicates.

### 4.5 Failure modes

| Failure | Detection | Recovery |
|---|---|---|
| User exports a match they reached via a stale shared link (match was surfaced in a prior run by a colleague) | `(user_id, run_id, match_id_hash)` triple invalid | 404 + log to unresolved with reason `INVALID_TRIPLE`. User-visible error. Acceptable — exports are per-user. |
| Export artifact generation fails (PDF service down) | Caught at step (c) | Return 500 to user; **do not** write the telemetry row (no signal yet — the user didn't get the export). |
| Telemetry write fails after artifact returned | Caught after step (e) | Buffer the row to `data/gold_signal_pending.jsonl` for retry. Never re-issue the artifact. |

### 4.6 What missing looks like

`INVALID_TRIPLE` is the most common unresolved reason for this path. Tracks "user is exporting something they reached out of band" — usually a shared link or a bookmarked URL. Monthly review.

---

## §5 Path C — `manual_self_report` (user clicks "I applied to this")

The GHP UI presents a small "I applied to this" button on every saved match. This is the highest-quality signal of the three — it is the user's explicit declaration that the matchmaker's output led to a real fundraising action.

### 5.1 Trigger event

User clicks an "I applied to this" button on a saved match. Variants worth tracking: "I'm planning to apply", "I applied", "I was awarded", "I was declined", "Not a fit after all". The last four are tier-2 signals; the first is the load-bearing one for the gold field.

### 5.2 Source system

GHP itself, same as Path B.

### 5.3 Mapping logic

1. The saved-match page exposes the buttons. Each button is a form post to `/matches/self-report/`.
2. The endpoint:
   a. Authenticates.
   b. Validates `(user_id, match_id_hash, button_variant)`. Match must belong to the user's saved list.
   c. Looks up the most-recent `run_id` within 30 days where this user-match pair was presented. If none, the user is reporting on a match that predates our retention window — log to unresolved with reason `NO_RECENT_RUN` and still record the event (the signal is real even if the run join is broken; see §5.6).
   d. Writes a `follow_up` row with `applied_to_external_signal: "manual_self_report"`, hashed user/match ids, the `run_id` (or null), `action: "apply_to"`, and `signal_payload_hash` derived from the button variant + the day.
   e. Returns a "Thanks — recorded" toast.

### 5.4 Idempotency

Per §2.2. Same button variant from same user on same match on same day → one row. Different button variant on same day → two rows (the user updated their state from "planning" to "applied"). Same button variant on a different day → two rows (sometimes intentional, e.g. the user pressed "I applied" before and is now pressing "I was awarded").

The button-variant transitions are themselves interesting; future work could capture them as a state machine, but v0 just stores each press as a row.

### 5.5 Failure modes

| Failure | Detection | Recovery |
|---|---|---|
| User reports on a match that predates retention | No recent run for the pair | Log unresolved with reason `NO_RECENT_RUN`. Still write the telemetry row with `run_id: null` (see §5.6). |
| Self-report endpoint receives a bad triple | Match doesn't belong to user's saved list | 400 + log to unresolved with reason `INVALID_TRIPLE`. |
| Telemetry write fails after user sees the toast | Caught post-response | Buffer to `data/gold_signal_pending.jsonl` for retry. |

### 5.6 The `run_id: null` exception

This path is the only one allowed to write a `follow_up` row with `run_id: null` — the user explicitly declared an outcome, and discarding that signal because we cannot join it to a specific run would be the wrong tradeoff. The matchmaker-instrumentation §3 envelope should be amended to allow `run_id: null` ONLY when `step == "follow_up" && applied_to_external_signal == "manual_self_report" && unresolved_reason == "NO_RECENT_RUN"`. All other `null` `run_id` values remain malformed.

Analysis-layer queries that join on `run_id` will exclude these rows; queries that count gold signals aggregated by user or by match will include them. The Q3 query in matchmaker-instrumentation §6 needs amendment: change `WHERE step = 'follow_up'` to `WHERE step = 'follow_up' AND run_id IS NOT NULL` for join-dependent analyses; add a second view for unresolved-but-real signals.

### 5.7 What missing looks like

`NO_RECENT_RUN` is the dominant unresolved reason here — and it is genuinely useful unresolved data, not a failure to ignore. Monthly review counts these to estimate the floor of "real fundraising actions GHP supported that our telemetry can't fully credit yet."

---

## §6 Build order

Per the synthesis principle in DETERMINISTIC_AGENTS.md §3, all three paths must be designed before the matchmaker ships, but they can be **built incrementally**:

1. **Path B first (`export_downloaded`).** Internal-only; no external system; lowest risk. Shipping the export endpoint with the telemetry write embedded is the v1 floor. Confirms the schema works end-to-end against real production data.
2. **Path C second (`manual_self_report`).** UI work plus an endpoint. Higher leverage than Path B because the signal is more direct, but requires UI design.
3. **Path A last (`kit_email_clicked`).** Depends on the alert workflow (DETERMINISTIC_AGENTS §4.4) actually shipping, which depends on the Kit connector being in `wphelper` and the alert generator being built. Highest engineering surface, also highest reach once live.

Each path's instrumentation must be live the first day its triggering feature ships. **Never ship the user-facing feature without the telemetry path** — that is the design-first move; capture without instrumentation is wasted observation.

---

## §7 Validation

The three paths together produce telemetry. The validation that the gold signal is *real* (and not a side-channel on something else) is:

- **Sanity check 1:** Do the three paths produce overlapping signal on the same `(user, match)` pairs over time? A match that was clicked-in-email, then exported, then self-reported as "I applied" is a single fundraising action expressed three ways. We should see this pattern in real usage; absence of overlap suggests an instrumentation gap.
- **Sanity check 2:** Does the gold signal rate per surfaced match track with users' reported satisfaction in qualitative interviews? If the gold rate is high but users say "this tool doesn't help me," something is wrong with what we're measuring as a signal. If the gold rate is low but users love it, we are undercounting (most likely Path C is missing rows because users aren't pressing the button — fix the UI).
- **Sanity check 3:** Does the gold rate drop when prompt versions are demoted (per the rubric's `would_demote_version` field)? If yes, the rubric is catching real quality regressions before the user-action signal does — that is the firmware compounding.

---

## §8 Maintenance

- Update this doc when a path's source system changes (Kit migration, GHP endpoint move).
- Add a new section if a fourth ingestion path lands (e.g. an OAuth integration with a foundation portal that confirms a real application submission).
- The `run_id: null` exception in §5.6 is load-bearing — any change to the envelope schema must preserve it explicitly.
- Monthly review of `data/gold_signal_unresolved.jsonl` and `data/gold_signal_pending.jsonl`. Both files must trend toward zero (pending) or stabilise at a known floor (unresolved); growth in either is a P1.
- This capture is the source of truth for what `applied_to_external_signal` means. If the matchmaker telemetry schema and this doc diverge, this doc wins for design intent and the schema is amended; if the live ingestion behaviour and this doc diverge, the doc is amended to match (with a §6 promotion-style note).

*Last updated: 2026-05-08 (v0 — design proposal; no path live yet).*
