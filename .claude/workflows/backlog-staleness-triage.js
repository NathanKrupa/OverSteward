// ABOUTME: Reusable backlog staleness-triage workflow — classifies a repo backlog against
// ABOUTME: current code (stale-vs-valid + feature value) with adversarial close-verification.
//
// Invoke:  Workflow({ name: 'backlog-staleness-triage', args: { repos: ['aigranthelper','grantspider'], cutoff: '2026-06-01' } })
// Args:
//   repos      (required) — array of repo slugs under `owner`
//   cutoff     (required) — only OPEN issues created strictly before this ISO date are triaged
//   owner      (optional) — GitHub owner, default 'NathanKrupa'
//   repoPaths  (optional) — { <repo>: <local checkout path> }; default '/home/natha/<repo>'
//
// Returns { total, gems, closeConfirmed, closeDisputed, rescope, keep, all }. The caller decides
// what to action — the workflow never closes or labels anything itself.
//
// Phases: Discover (per-repo current-state baseline + pre-cutoff issue list) → Classify (one
// read-only classifier per issue, judged against its repo baseline) → Verify (adversarial
// close-check on every REDUNDANT/OVERTAKEN candidate, so nothing with residual scope is closed).

export const meta = {
  name: 'backlog-staleness-triage',
  description: 'Triage a repo backlog vs current code: stale-vs-valid + feature value, with adversarial close-verification. args:{repos:[...],cutoff:"YYYY-MM-DD",owner?,repoPaths?}',
  whenToUse: 'When a backlog has drifted and old issues may describe a system that has since changed — surfaces close/rescope candidates AND high-value not-yet-built features (gems).',
  phases: [
    { title: 'Discover', detail: 'per-repo: build current-state baseline + list pre-cutoff open issues' },
    { title: 'Classify', detail: 'one read-only classifier per issue, vs its repo baseline', model: 'sonnet' },
    { title: 'Verify', detail: 'adversarial close-check on each REDUNDANT/OVERTAKEN candidate' },
  ],
}

const cfg = typeof args === 'string' ? JSON.parse(args) : (args || {})
const repos = cfg.repos || []
const cutoff = cfg.cutoff
if (!repos.length || !cutoff) throw new Error('args must be { repos:[...], cutoff:"YYYY-MM-DD" }')
const owner = cfg.owner || 'NathanKrupa'
const pathOf = (r) => (cfg.repoPaths && cfg.repoPaths[r]) || `/home/natha/${r}`

const WORKLIST_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    issues: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: { number: { type: 'integer' }, title: { type: 'string' } },
        required: ['number', 'title'],
      },
    },
  },
  required: ['issues'],
}

const CLASSIFY_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    verdict: { type: 'string', enum: ['STILL_VALID', 'REDUNDANT', 'PARTIAL', 'OVERTAKEN', 'NEEDS_RESCOPE'] },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    value: { type: 'string', enum: ['high', 'medium', 'low'], description: 'value to the project IF this work were done (independent of staleness)' },
    is_gem: { type: 'boolean', description: 'true only if a NOT-yet-built feature that genuinely fits the project and would be strong' },
    recommended_action: { type: 'string', enum: ['CLOSE', 'KEEP', 'RESCOPE', 'PRIORITIZE'] },
    rationale: { type: 'string', description: 'one or two sentences citing concrete current-code evidence' },
    evidence: { type: 'string', description: 'specific files / modules / PRs / issues that justify the verdict' },
  },
  required: ['verdict', 'confidence', 'value', 'is_gem', 'recommended_action', 'rationale', 'evidence'],
}

const VERIFY_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    agrees_close: { type: 'boolean' },
    reason: { type: 'string', description: 'why closing is/is not safe — cite the residual scope if any remains' },
  },
  required: ['agrees_close', 'reason'],
}

const baselinePrompt = (repo) => `Read-only investigation. Repo at ${pathOf(repo)}. Do NOT modify anything.

Produce a CURRENT-STATE feature inventory — a baseline of what is actually BUILT today — so old GitHub issues can be judged for staleness. This is NOT a code review; it's a "what exists now" map.

Cover:
1. Top-level structure (apps/packages and one line each).
2. Core capabilities shipped now — for each: fully-built / partial / scaffolding.
3. Major recent shifts (scan \`git log --oneline --since\` ~8 weeks; use origin's default + protected branches) — renames, dropped tooling, replaced subsystems, big epics that would OBSOLETE older issues. Call these out explicitly.
4. Key domain models and where they live.
5. Branch model (default vs protected branch, promotion flow) if non-trivial.

Lead with the capability table; END with the recent-shifts list and branch note. Keep it tight and structured — your full text becomes the ground-truth baseline injected into every per-issue classifier.`

const worklistPrompt = (repo) => `Read-only. List every OPEN issue in ${owner}/${repo} created strictly before ${cutoff}.

Run exactly:
\`gh issue list --repo ${owner}/${repo} --state open --limit 400 --json number,title,createdAt --jq '[.[] | select(.createdAt < "${cutoff}") | {number, title}]'\`

Return the result as { "issues": [ {number, title}, ... ] }. Do not editorialize.`

const classifyPrompt = (it, baseline) => `Read-only triage of ONE GitHub issue. Do NOT modify anything. Be efficient — this is one of many.

CURRENT-STATE BASELINE for ${it.repo} (ground truth — what is BUILT today + recent shifts that obsolete old issues):
${baseline}
---
Issue: ${owner}/${it.repo}#${it.number} — "${it.title}"

Steps:
1. Read the issue: \`gh issue view ${it.number} --repo ${owner}/${it.repo} --json title,body,labels,comments\`
2. Check its ask against the LIVE code in ${pathOf(it.repo)} — targeted grep/ls for the feature/module/model it names (don't over-explore).

Classify:
- verdict: STILL_VALID (genuinely not built, still wanted) | REDUNDANT (already built — cite where) | PARTIAL (substrate exists, some asked work remains) | OVERTAKEN (premise obsoleted by an architecture/branch/tooling shift) | NEEDS_RESCOPE (still relevant but the ask must be substantially rewritten for today)
- value: high | medium | low — value to the project IF done, independent of staleness.
- is_gem: TRUE only for a NOT-yet-built feature that genuinely fits and would be a strong addition. Be discerning, not generous.
- recommended_action: CLOSE | KEEP | RESCOPE | PRIORITIZE
- rationale: 1-2 sentences with concrete evidence.
- evidence: the specific files/modules/PRs/issues.

Return ONLY the structured object.`

const verifyPrompt = (it, c) => `Adversarial check before we CLOSE a GitHub issue. Default to NOT closing if any real residual scope exists. Read-only.

Issue: ${owner}/${it.repo}#${it.number} — "${it.title}"
A first classifier judged it ${c.verdict} (action CLOSE): "${c.rationale}" / evidence: "${c.evidence}".

Try to REFUTE the close. Re-read \`gh issue view ${it.number} --repo ${owner}/${it.repo} --json title,body,labels,comments\` and spot-check the live code in ${pathOf(it.repo)}. Is EVERY part of the issue's ask truly already built or truly obsolete? If even a meaningful slice remains real and unbuilt, closing is wrong.

Return: agrees_close (true only if closing is genuinely safe), reason (cite the residual scope if found).`

// ── Discover: baseline + worklist per repo, in parallel ──
phase('Discover')
const perRepo = await parallel(repos.map((repo) => async () => {
  const baseline = await agent(baselinePrompt(repo), { label: `baseline:${repo}`, phase: 'Discover', agentType: 'Explore' })
  const wl = await agent(worklistPrompt(repo), { label: `worklist:${repo}`, phase: 'Discover', agentType: 'Explore', schema: WORKLIST_SCHEMA })
  return { repo, baseline, items: (wl && wl.issues) || [] }
}))
const baselines = {}
perRepo.filter(Boolean).forEach((pr) => { baselines[pr.repo] = pr.baseline })
const WORK = perRepo.filter(Boolean).flatMap((pr) => pr.items.map((it) => ({ repo: pr.repo, number: it.number, title: it.title })))
log(`Discover done: ${WORK.length} issues across ${repos.length} repo(s)`)

// ── Classify (read-only, vs baseline) → Verify (adversarial, close-candidates only) ──
phase('Classify')
const results = await pipeline(
  WORK,
  (it) => agent(classifyPrompt(it, baselines[it.repo] || ''), { label: `classify:${it.repo}#${it.number}`, phase: 'Classify', model: 'sonnet', agentType: 'Explore', schema: CLASSIFY_SCHEMA })
            .then((c) => ({ ...it, ...c }))
            .catch(() => ({ ...it, verdict: 'ERROR', confidence: 'low', value: 'low', is_gem: false, recommended_action: 'KEEP', rationale: 'classifier failed', evidence: '' })),
  (c, it) => {
    const closeCandidate = c.verdict === 'REDUNDANT' || c.verdict === 'OVERTAKEN'
    if (!closeCandidate) return c
    return agent(verifyPrompt(it, c), { label: `verify:${it.repo}#${it.number}`, phase: 'Verify', agentType: 'Explore', schema: VERIFY_SCHEMA })
      .then((v) => ({ ...c, verify_agrees_close: v.agrees_close, verify_reason: v.reason }))
      .catch(() => ({ ...c, verify_agrees_close: null, verify_reason: 'verifier failed' }))
  },
)

const clean = results.filter(Boolean)
const gems = clean.filter((r) => r.is_gem || r.recommended_action === 'PRIORITIZE')
const closeConfirmed = clean.filter((r) => (r.verdict === 'REDUNDANT' || r.verdict === 'OVERTAKEN') && r.verify_agrees_close === true)
const closeDisputed = clean.filter((r) => (r.verdict === 'REDUNDANT' || r.verdict === 'OVERTAKEN') && r.verify_agrees_close !== true)
const rescope = clean.filter((r) => r.verdict === 'NEEDS_RESCOPE' || (r.verdict === 'PARTIAL' && r.recommended_action === 'RESCOPE'))
const keep = clean.filter((r) => r.recommended_action === 'KEEP' && !r.is_gem)

log(`Triage done: ${clean.length} classified — ${gems.length} gems, ${closeConfirmed.length} close-confirmed, ${closeDisputed.length} close-disputed, ${rescope.length} rescope, ${keep.length} keep`)

return { total: clean.length, gems, closeConfirmed, closeDisputed, rescope, keep, all: clean }
