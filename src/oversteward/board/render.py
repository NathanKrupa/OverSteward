# ABOUTME: Renders a BoardReport as the Estate Board page — decisions first, counts beside them.
# ABOUTME: Pure: takes the report, returns HTML; publishing is the outer script's job.

"""The Estate Board as a page.

Summary before detail: the tiles say how much waits, the queue says what, the
epic table says why, and the repository table gives the scale. Every issue
title is escaped — it is text people typed into GitHub, never markup.

A decision that carries verbs renders a card: one form per verb, aimed at the
decision's issue through ``data-`` attributes, driven by ``cards.js`` — the
one script on the page, which writes to GitHub through the viewer's own
connector and never stores anything here.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

from oversteward.board.assemble import Action, BoardReport, Decision, DecisionKind
from oversteward.board.epics import DECISION_HEALTH, Epic, EpicHealth

#: The connector's display name the page passes to every ``callTool``. ``cards.js``
#: carries the same string as ``SERVER``; ``test_render`` pins the two equal. The
#: artifact publish resolves the manifest's server segment to this display name
#: and reports it — that report is read by the publishing session, not by code.
CONNECTOR = "GitHub"

_CARDS_JS = Path(__file__).with_name("cards.js")

_STYLE = """
:root{
  --bg:#F5F6F8; --panel:#FFFFFF; --line:#DCE0E6; --line-soft:#ECEEF2;
  --ink:#1B2230; --ink-2:#4E5868; --ink-3:#7C8696;
  --accent:#9C7226; --accent-soft:#F3EAD6;
  --good:#2E7D4F; --good-soft:#E3F1E8;
  --warn:#B5651D; --warn-soft:#F8E9DA;
  --crit:#B03A2E; --crit-soft:#F7E1DE;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#13171E; --panel:#1A1F28; --line:#2B323D; --line-soft:#232932;
    --ink:#E8EBF0; --ink-2:#A6AFBD; --ink-3:#6F7987;
    --accent:#D4A94E; --accent-soft:#2E2718;
    --good:#6FC48F; --good-soft:#18301F;
    --warn:#E3955A; --warn-soft:#34241A;
    --crit:#E8756A; --crit-soft:#3A1F1C;
  }
}
:root[data-theme="dark"]{
  --bg:#13171E; --panel:#1A1F28; --line:#2B323D; --line-soft:#232932;
  --ink:#E8EBF0; --ink-2:#A6AFBD; --ink-3:#6F7987;
  --accent:#D4A94E; --accent-soft:#2E2718;
  --good:#6FC48F; --good-soft:#18301F;
  --warn:#E3955A; --warn-soft:#34241A;
  --crit:#E8756A; --crit-soft:#3A1F1C;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 "IBM Plex Sans",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none;border-bottom:1px solid var(--line)}
a:hover{border-bottom-color:var(--accent)}
a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.wrap{max-width:1120px;margin:0 auto;padding-block:32px 64px;padding-inline:24px;display:flex;flex-direction:column;gap:28px}
header{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:12px;border-bottom:1px solid var(--line);padding-bottom:16px}
h1{font:300 40px/1 "Newsreader",Georgia,serif;margin:0;letter-spacing:-.01em;text-wrap:balance}
h1 em{font-style:normal;font-weight:500;color:var(--accent)}
.stamp{font:13px "IBM Plex Mono",monospace;color:var(--ink-3)}
.stamp b{color:var(--ink-2);font-weight:500}
.eyebrow{font:500 11px/1 "IBM Plex Sans",sans-serif;text-transform:uppercase;letter-spacing:.12em;color:var(--ink-3);margin:0 0 10px}
h2{font:500 22px/1.2 "Newsreader",Georgia,serif;margin:0 0 12px;text-wrap:balance}
h3{font:500 13px/1 "IBM Plex Sans",sans-serif;text-transform:uppercase;letter-spacing:.08em;color:var(--ink-2);margin:18px 0 6px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:16px 18px;display:flex;flex-direction:column;gap:6px}
.tile .n{font:300 44px/1 "Newsreader",Georgia,serif;font-variant-numeric:tabular-nums}
.tile .l{font-weight:500;color:var(--ink-2)}
.tile .s{font-size:13px;color:var(--ink-3)}
.tile.crit{border-left:4px solid var(--crit)} .tile.crit .n{color:var(--crit)}
.tile.warn{border-left:4px solid var(--warn)} .tile.warn .n{color:var(--warn)}
.tile.acc{border-left:4px solid var(--accent)} .tile.acc .n{color:var(--accent)}
.tile.good{border-left:4px solid var(--good)} .tile.good .n{color:var(--good)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:18px 20px}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th{font:500 11px/1 "IBM Plex Sans",sans-serif;text-transform:uppercase;letter-spacing:.1em;color:var(--ink-3);text-align:right;padding:0 10px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child{text-align:left;padding-left:0}
th.t,td.t{text-align:left}
td{padding:8px 10px;border-bottom:1px solid var(--line-soft);text-align:right;white-space:nowrap;vertical-align:top}
td.t{white-space:normal;max-width:38ch}
tr:last-child td{border-bottom:0}
td.repo{font-weight:500}
td.dim,span.dim{color:var(--ink-3)}
tfoot td{font-weight:600;border-top:1px solid var(--line)}
.pill{display:inline-block;font:500 12px/1 "IBM Plex Sans",sans-serif;padding:5px 9px;border-radius:999px;white-space:nowrap}
.pill.good{background:var(--good-soft);color:var(--good)}
.pill.warn{background:var(--warn-soft);color:var(--warn)}
.pill.crit{background:var(--crit-soft);color:var(--crit)}
.pill.acc{background:var(--accent-soft);color:var(--accent)}
.pill.mute{background:var(--line-soft);color:var(--ink-2)}
.list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column}
.list li{display:grid;grid-template-columns:118px minmax(110px,180px) 1fr auto;gap:14px;align-items:baseline;padding:10px 0;border-bottom:1px solid var(--line-soft)}
.list li:last-child{border-bottom:0}
.list .repo{font-weight:500;color:var(--ink-2)}
.list .id{font:13px "IBM Plex Mono",monospace;color:var(--ink-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.list .t{min-width:0}
.list .t .ask{display:block;color:var(--ink-2);font-size:13px}
.empty{color:var(--ink-2);padding:14px 0}
.card{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:8px;align-items:flex-start;margin:0}
.card textarea{flex:1 1 320px;min-height:56px;padding:8px 10px;font:14px/1.4 "IBM Plex Sans",system-ui,sans-serif;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:4px;resize:vertical}
.card textarea:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.card button{font:500 13px/1 "IBM Plex Sans",sans-serif;padding:10px 14px;border-radius:4px;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer;min-height:44px}
.card button:hover{filter:brightness(1.08)}
.card button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.card button:disabled{opacity:.55;cursor:default}
.card .status{flex-basis:100%;margin:0;font-size:13px;color:var(--ink-2);min-height:1em}
.card.pending .status{color:var(--warn)}
.card.done .status{color:var(--good)}
.card.failed .status{color:var(--crit)}
.card.done textarea,.card.done button{display:none}
li[data-state="done"]>.repo,li[data-state="done"]>.id,li[data-state="done"]>.t,li[data-state="done"]>.pill{opacity:.5}
.mono{font:13px "IBM Plex Mono",monospace}
.note{font-size:13px;color:var(--ink-3);border-top:1px solid var(--line);padding-top:14px;max-width:70ch}
.note code{font:12px "IBM Plex Mono",monospace;background:var(--line-soft);padding:2px 5px;border-radius:3px}
@media (max-width:760px){.list li{grid-template-columns:1fr auto;grid-template-rows:auto auto}.list .t{grid-column:1/-1}h1{font-size:32px}}
"""

_HEALTH_PILL = {
    EpicHealth.ACTIVE: ("good", "active"),
    EpicHealth.QUIET: ("mute", "quiet"),
    EpicHealth.STALLED: ("warn", "stalled"),
    EpicHealth.LABEL_ONLY: ("crit", "label only"),
    EpicHealth.PARENT_CLOSED: ("crit", "parent closed"),
    EpicHealth.DONE_OPEN: ("acc", "done, still open"),
    EpicHealth.CHILDLESS: ("warn", "no children"),
}


def _days(n: int | None) -> str:
    if n is None:
        return "—"
    if n == 0:
        return "today"
    return f"{n} day{'s' if n != 1 else ''}"


def _card(action: Action) -> str:
    required = " required" if action.note_required else ""
    return (
        '<form class="card">'
        f'<textarea name="note" rows="2" placeholder="{escape(action.prompt, quote=True)}"'
        f' aria-label="{escape(action.prompt, quote=True)}"{required}></textarea>'
        f'<button type="submit" data-verb="{action.verb.value}"'
        f' data-note-required="{int(action.note_required)}">{escape(action.label)}</button>'
        '<p class="status" aria-live="polite"></p></form>'
    )


def _decision_li(d: Decision) -> str:
    if d.kind is DecisionKind.ANSWER:
        pill = f'<span class="pill {"crit" if d.stale else "warn"}">{_days(d.age_days)}{" · stale" if d.stale else ""}</span>'
    else:
        pill = f'<span class="pill mute">{_days(d.age_days)}</span>'
    attrs = ""
    cards = ""
    if d.target is not None and d.actions:
        attrs = (
            f' data-owner="{escape(d.target.owner, quote=True)}"'
            f' data-repo="{escape(d.target.repo, quote=True)}"'
            f' data-number="{d.target.number}"'
        )
        cards = "".join(_card(a) for a in d.actions)
    return (
        f'<li{attrs}><span class="repo">{escape(d.repo)}</span>'
        f'<span class="id"><a href="{escape(d.url, quote=True)}">{escape(d.ref)}</a></span>'
        f'<span class="t">{escape(d.title)}<span class="ask">{escape(d.ask)}</span></span>'
        f"{pill}{cards}</li>"
    )


def _decisions(report: BoardReport) -> str:
    answers = [d for d in report.decisions if d.kind is DecisionKind.ANSWER]
    epics = [d for d in report.decisions if d.kind is DecisionKind.EPIC]
    if not report.decisions:
        return '<p class="empty">Nothing waits on you. Every agent question is answered and every epic is moving.</p>'
    parts = []
    if answers:
        parts.append(f"<h3>Agents waiting on an answer · {len(answers)}</h3>")
        parts.append('<ul class="list">' + "".join(_decision_li(d) for d in answers) + "</ul>")
    if epics:
        parts.append(f"<h3>Epics wanting a ruling · {len(epics)}</h3>")
        parts.append('<ul class="list">' + "".join(_decision_li(d) for d in epics) + "</ul>")
    return "".join(parts)


def _epic_row(epic: Epic, now: datetime) -> str:
    health = epic.health(now)
    cls, label = _HEALTH_PILL[health]
    if epic.parent is not None:
        key = f'<a href="{escape(epic.parent.url, quote=True)}">{escape(epic.key)}</a>'
    else:
        key = escape(epic.key)
    title = (
        escape(epic.parent.title)
        if epic.parent is not None
        else '<span class="dim">no epic issue</span>'
    )
    close_flag = (
        ' <span class="dim">· last motion was a close</span>'
        if epic.last_motion_was_close and epic.open_children
        else ""
    )
    return (
        f'<tr><td class="mono">{key}</td><td class="t">{title}</td>'
        f"<td>{epic.open_children}</td><td>{epic.closed_children}</td>"
        f"<td>{_days(epic.days_quiet(now))}{close_flag}</td>"
        f'<td><span class="pill {cls}">{label}</span></td></tr>'
    )


def _epic_tables(report: BoardReport) -> str:
    by_repo: dict[str, list[Epic]] = {}
    for epic in report.epics:
        by_repo.setdefault(epic.repo, []).append(epic)
    if not by_repo:
        return '<p class="empty">No epics in any repository.</p>'
    order = {
        EpicHealth.PARENT_CLOSED: 0,
        EpicHealth.DONE_OPEN: 1,
        EpicHealth.STALLED: 2,
        EpicHealth.LABEL_ONLY: 3,
        EpicHealth.CHILDLESS: 4,
        EpicHealth.QUIET: 5,
        EpicHealth.ACTIVE: 6,
    }
    parts = []
    for repo, epics in by_repo.items():
        epics.sort(
            key=lambda e: (
                order[e.health(report.generated_at)],
                -(e.days_quiet(report.generated_at) or 0),
            )
        )
        deciding = sum(e.health(report.generated_at) in DECISION_HEALTH for e in epics)
        parts.append(f"<h3>{escape(repo)} · {len(epics)} epics · {deciding} wanting a ruling</h3>")
        parts.append(
            '<div class="scroll"><table><thead><tr><th>Epic</th><th class="t">Title</th>'
            "<th>Open</th><th>Closed</th><th>Quiet for</th><th>Health</th></tr></thead><tbody>"
            + "".join(_epic_row(e, report.generated_at) for e in epics)
            + "</tbody></table></div>"
        )
    return "".join(parts)


def _repo_table(report: BoardReport) -> str:
    rows = "".join(
        f'<tr><td class="repo">{escape(r.repo)}</td><td>{r.open}</td><td>{r.needs_input}</td>'
        f"<td>{r.ready}</td><td>{r.in_progress}</td><td>{r.needs_scoping}</td><td>{r.epics}</td></tr>"
        for r in report.repos
    )
    t = report.repos
    foot = (
        f"<tr><td>Total</td><td>{sum(r.open for r in t)}</td><td>{sum(r.needs_input for r in t)}</td>"
        f"<td>{sum(r.ready for r in t)}</td><td>{sum(r.in_progress for r in t)}</td>"
        f"<td>{sum(r.needs_scoping for r in t)}</td><td>{sum(r.epics for r in t)}</td></tr>"
    )
    return (
        '<div class="scroll"><table><thead><tr><th>Repository</th><th>Open</th><th>Waiting on you</th>'
        "<th>Ready</th><th>In progress</th><th>Needs scoping</th><th>Epics</th></tr></thead>"
        f"<tbody>{rows}</tbody><tfoot>{foot}</tfoot></table></div>"
    )


def render(report: BoardReport) -> str:
    now = report.generated_at
    answers = [d for d in report.decisions if d.kind is DecisionKind.ANSWER]
    stale = sum(d.stale for d in answers)
    epic_decisions = [d for d in report.decisions if d.kind is DecisionKind.EPIC]
    ready = sum(r.ready for r in report.repos)
    in_progress = sum(r.in_progress for r in report.repos)
    scoping = sum(r.needs_scoping for r in report.repos)
    stamp = now.strftime("%Y-%m-%d · %H:%M UTC")
    repo_count = len(report.repos)

    def per_repo(attr: str) -> str:
        parts = [f"{escape(r.repo)} {getattr(r, attr)}" for r in report.repos if getattr(r, attr)]
        return " · ".join(parts) if parts else "none"

    return f"""<title>Estate Board</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,300;6..72,500&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>{_STYLE}</style>
<div class="wrap">
<header>
  <h1>The <em>Estate</em> Board</h1>
  <div class="stamp">snapshot <b>{stamp}</b> · {repo_count} repositories</div>
</header>

<section>
  <p class="eyebrow">Attention</p>
  <div class="tiles">
    <div class="tile {"crit" if answers else "good"}"><span class="n">{len(answers)}</span><span class="l">Agents waiting on you</span><span class="s">{f"{stale} stale ≥ 48h" if stale else "none stale"}</span></div>
    <div class="tile {"warn" if epic_decisions else "good"}"><span class="n">{len(epic_decisions)}</span><span class="l">Epics wanting a ruling</span><span class="s">of {len(report.epics)} live epics</span></div>
    <div class="tile acc"><span class="n">{ready}</span><span class="l">Ready to dispatch</span><span class="s">{per_repo("ready")}</span></div>
    <div class="tile good"><span class="n">{in_progress}</span><span class="l">Agents in flight</span><span class="s">{scoping} awaiting scoping</span></div>
  </div>
</section>

<section class="panel" id="decisions">
  <p class="eyebrow">Needs a decision</p>
  <h2>The queue</h2>
  {_decisions(report)}
</section>

<section class="panel" id="epics">
  <p class="eyebrow">Lines of inquiry</p>
  <h2>Epic health</h2>
  {_epic_tables(report)}
</section>

<section class="panel">
  <p class="eyebrow">By repository</p>
  {_repo_table(report)}
</section>

<p class="note">Snapshot derived entirely from GitHub issues by <code>scripts/estate_board.py</code> — nothing here is stored anywhere but GitHub. An epic is an <code>epic:</code> label or an epic-titled issue; its motion is its children's, never the parent's own edits. Quiet after 14 days, stalled after 30. Each card is one ruling written to GitHub through your own GitHub connector: an answer posts the comment <code>/answer</code> would and moves the issue to <code>ready-for-agent</code>; closing, shelving and reopening post the ruling and change the state. A tap stays pending until GitHub shows the change; the page never writes anywhere else. Rebuild the board to see the queue after a ruling.</p>
</div>
<script>{_CARDS_JS.read_text(encoding="utf-8")}</script>
"""


__all__ = ["CONNECTOR", "render"]
