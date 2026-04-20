# ABOUTME: Pipeline dashboard for the four orchestration repos.
# ABOUTME: Status table + in-flight + scoping candidates + 30d metrics; appends a snapshot row per repo to data/pipeline_history.jsonl.

from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from registry import OWNER, dispatch_targets

# Display order for the dashboard table. Any registry-declared dispatch target
# not listed here falls through to the end, in registry order, so a newly added
# fifth repo appears last without breaking the existing four-repo layout.
DISPLAY_ORDER = ("aigranthelper", "grantspider", "wphelper", "ai-assistants")


def _ordered_targets() -> tuple[str, ...]:
    targets = dispatch_targets()
    known = tuple(r for r in DISPLAY_ORDER if r in targets)
    extras = tuple(r for r in targets if r not in DISPLAY_ORDER)
    return known + extras


REPOS = _ordered_targets()
REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = REPO_ROOT / ".claude" / "skills" / "project-status" / "state.json"
SNAPSHOT_PATH = REPO_ROOT / "data" / "pipeline_history.jsonl"
SCOPING_SURFACE_THRESHOLD = 2
GH_LIMIT = 200
METRIC_WINDOW_DAYS = 30
BRANCH_RE = re.compile(r"^(fix|feat|ci|refactor|cleanup)/issue-(\d+)-")

# Issues carrying any of these labels are not "scoping candidates" -- they're
# already processed, in flight, declined, or deliberately deferred.
UNSCOPED_EXCLUDES = frozenset({
    "ready-for-agent",
    "agent-in-progress",
    "agent-done",
    "reject-close",
    "needs-input",
    "wontfix",
    "duplicate",
    "invalid",
    "backlog",
})


def gh_json(args: list[str]) -> list[dict]:
    proc = subprocess.run(
        ["gh", *args], capture_output=True, text=True, encoding="utf-8"
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh {' '.join(args)} failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    out = proc.stdout.strip()
    return json.loads(out) if out else []


def fetch_repo(repo: str, since_iso: str, window_iso: str) -> dict:
    full = f"{OWNER}/{repo}"
    limit = str(GH_LIMIT)
    open_issues = gh_json([
        "issue", "list", "--repo", full, "--state", "open",
        "--limit", limit, "--json", "number,title,url,labels,createdAt,updatedAt",
    ])
    open_prs = gh_json([
        "pr", "list", "--repo", full, "--state", "open",
        "--limit", limit, "--json", "number,headRefName,title,url",
    ])
    closed_issues = gh_json([
        "issue", "list", "--repo", full, "--state", "closed",
        "--search", f"closed:>={since_iso}",
        "--limit", limit, "--json", "number",
    ])
    merged_prs = gh_json([
        "pr", "list", "--repo", full, "--state", "merged",
        "--search", f"merged:>={since_iso}",
        "--limit", limit, "--json", "number",
    ])
    merged_prs_window = gh_json([
        "pr", "list", "--repo", full, "--state", "merged",
        "--search", f"merged:>={window_iso}",
        "--limit", limit, "--json", "number,createdAt,mergedAt",
    ])
    closed_unmerged_window = gh_json([
        "pr", "list", "--repo", full, "--state", "closed",
        "--search", f"-is:merged closed:>={window_iso}",
        "--limit", limit, "--json", "number",
    ])
    return {
        "repo": repo,
        "open_issues": open_issues,
        "open_prs": open_prs,
        "closed_issue_count": len(closed_issues),
        "merged_pr_count": len(merged_prs),
        "merged_prs_window": merged_prs_window,
        "closed_unmerged_count_window": len(closed_unmerged_window),
    }


def fetch_all(since_iso: str, window_iso: str) -> list[dict]:
    with ThreadPoolExecutor(max_workers=len(REPOS)) as ex:
        futures = {
            ex.submit(fetch_repo, r, since_iso, window_iso): r for r in REPOS
        }
        results: list[dict] = []
        for fut, repo in futures.items():
            try:
                results.append(fut.result())
            except Exception as e:  # noqa: BLE001
                results.append({"repo": repo, "error": str(e)})
    results.sort(key=lambda d: REPOS.index(d["repo"]))
    return results


def labels_of(issue: dict) -> set[str]:
    return {lbl["name"] for lbl in issue.get("labels", [])}


def read_state() -> tuple[datetime, bool]:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data["last_checked"].replace("Z", "+00:00"))
        return ts.astimezone(timezone.utc), False
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
        return datetime.now(timezone.utc) - timedelta(hours=24), True


def write_state(now: datetime) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({"last_checked": iso_z(now)}) + "\n", encoding="utf-8"
    )


def iso_z(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def format_since(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d %H:%M UTC")


def pick_scoping_candidate(
    open_issues: list[dict],
) -> tuple[dict, str] | None:
    """Return (issue, source) where source is 'labeled' or 'fallback'.

    Priority 1: oldest issue labeled `needs-scoping`.
    Priority 2: oldest issue carrying none of the UNSCOPED_EXCLUDES labels
    (i.e., not already processed, in flight, declined, or deferred).
    """
    labeled = [i for i in open_issues if "needs-scoping" in labels_of(i)]
    if labeled:
        labeled.sort(key=lambda i: i["createdAt"])
        return labeled[0], "labeled"
    fallback = [
        i for i in open_issues if not (labels_of(i) & UNSCOPED_EXCLUDES)
    ]
    if fallback:
        fallback.sort(key=lambda i: i["createdAt"])
        return fallback[0], "fallback"
    return None


def humanize_age(created: datetime, now: datetime) -> str:
    delta = now - created
    if delta.days < 1:
        hours = max(1, delta.seconds // 3600)
        return f"{hours}h"
    if delta.days < 30:
        return f"{delta.days}d"
    return f"{delta.days // 30}mo"


def humanize_hours(h: float) -> str:
    if h < 24:
        return f"{h:.1f}h"
    return f"{h / 24:.1f}d"


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def pr_turnaround_hours(merged_prs: list[dict]) -> list[float]:
    """Hours from PR creation to PR merge, per merged PR in the window."""
    out: list[float] = []
    for pr in merged_prs:
        created = _parse_iso(pr["createdAt"])
        merged = _parse_iso(pr["mergedAt"])
        out.append((merged - created).total_seconds() / 3600.0)
    return out


def needs_input_ages_hours(open_issues: list[dict], now: datetime) -> list[float]:
    """Hours each currently-open `needs-input` issue has been sitting.

    Uses `updatedAt` as the best-available proxy for when the agent filed its
    question. Precise timeline (label-applied-at) would require an extra
    per-issue timeline fetch -- deferred.
    """
    out: list[float] = []
    for issue in open_issues:
        if "needs-input" not in labels_of(issue):
            continue
        ts = issue.get("updatedAt") or issue.get("createdAt")
        if not ts:
            continue
        age = (now - _parse_iso(ts)).total_seconds() / 3600.0
        out.append(age)
    return out


def compute_metrics(results: list[dict], now: datetime) -> dict:
    """Aggregate 30d pipeline metrics across all non-errored repos."""
    turnaround: list[float] = []
    merged_count = 0
    closed_unmerged_count = 0
    ni_ages: list[float] = []
    for r in results:
        if "error" in r:
            continue
        turnaround.extend(pr_turnaround_hours(r["merged_prs_window"]))
        merged_count += len(r["merged_prs_window"])
        closed_unmerged_count += r["closed_unmerged_count_window"]
        ni_ages.extend(needs_input_ages_hours(r["open_issues"], now))
    total_closed = merged_count + closed_unmerged_count
    merge_rate = (merged_count / total_closed) if total_closed else None
    return {
        "turnaround_hours": turnaround,
        "merged_count": merged_count,
        "closed_unmerged_count": closed_unmerged_count,
        "merge_rate": merge_rate,
        "ni_ages_hours": ni_ages,
    }


def render_metrics(metrics: dict) -> list[str]:
    lines: list[str] = [f"Pipeline metrics (last {METRIC_WINDOW_DAYS}d):", ""]
    turnaround = metrics["turnaround_hours"]
    if turnaround:
        med = statistics.median(turnaround)
        mx = max(turnaround)
        lines.append(
            f"- PR turnaround (open -> merge): median {humanize_hours(med)}, "
            f"max {humanize_hours(mx)} across {len(turnaround)} merged PRs"
        )
    else:
        lines.append(
            f"- PR turnaround: no merged PRs in last {METRIC_WINDOW_DAYS}d"
        )

    merged = metrics["merged_count"]
    unmerged = metrics["closed_unmerged_count"]
    rate = metrics["merge_rate"]
    if rate is not None:
        lines.append(
            f"- Merge rate: {rate:.0%} ({merged} merged / "
            f"{merged + unmerged} closed; {unmerged} closed-unmerged)"
        )
    else:
        lines.append(
            f"- Merge rate: no closed PRs in last {METRIC_WINDOW_DAYS}d"
        )

    ni = metrics["ni_ages_hours"]
    if ni:
        med = statistics.median(ni)
        mx = max(ni)
        lines.append(
            f"- Needs-input age (currently open): median {humanize_hours(med)}, "
            f"max {humanize_hours(mx)} across {len(ni)} issue(s)"
        )
    else:
        lines.append("- Needs-input age: no open needs-input issues")

    lines.append("")
    return lines


def snapshot_row(result: dict, now: datetime, since: datetime) -> dict:
    open_issues = result["open_issues"]
    label_count = lambda name: sum(  # noqa: E731
        1 for i in open_issues if name in labels_of(i)
    )
    in_flight_count = sum(
        1
        for pr in result["open_prs"]
        if BRANCH_RE.match(pr["headRefName"])
    )
    return {
        "ts": iso_z(now),
        "since": iso_z(since),
        "repo": result["repo"],
        "open_issues": len(open_issues),
        "open_prs": len(result["open_prs"]),
        "ready_queue": label_count("ready-for-agent"),
        "needs_scoping": label_count("needs-scoping"),
        "needs_input": label_count("needs-input"),
        "in_flight": in_flight_count,
        "closed_since_last": result["closed_issue_count"],
        "merged_since_last": result["merged_pr_count"],
    }


def write_snapshot(results: list[dict], now: datetime, since: datetime) -> None:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SNAPSHOT_PATH.open("a", encoding="utf-8") as f:
        for r in results:
            if "error" in r:
                continue
            f.write(json.dumps(snapshot_row(r, now, since)) + "\n")


def render(
    results: list[dict],
    since: datetime,
    is_first_run: bool,
    now: datetime,
    metrics: dict,
) -> str:
    lines: list[str] = []
    lines.append(f"Project pipeline status -- since {format_since(since)}")
    if is_first_run:
        lines.append(
            '(first run -- "since" window is last 24h; '
            "future runs will measure from this moment)"
        )
    lines.append("")

    cap_hits: list[str] = []
    totals = {"open_issues": 0, "open_prs": 0, "closed": 0, "merged": 0,
              "ready": 0, "scoping": 0}

    lines.append(
        "| Project         | Open issues | Open PRs | Closed issues | "
        "Merged PRs | Ready queue | Needs scoping |"
    )
    lines.append(
        "|-----------------|-------------|----------|---------------|"
        "------------|-------------|---------------|"
    )
    for r in results:
        repo = r["repo"]
        if "error" in r:
            lines.append(
                f"| {repo:<15} | error | error | error | error | error | error |"
            )
            continue
        open_issues = r["open_issues"]
        ready = sum(1 for i in open_issues if "ready-for-agent" in labels_of(i))
        scoping = sum(1 for i in open_issues if "needs-scoping" in labels_of(i))
        oi = len(open_issues)
        op = len(r["open_prs"])
        ci = r["closed_issue_count"]
        mp = r["merged_pr_count"]
        for name, val in (
            ("open issues", oi), ("open PRs", op),
            ("closed issues", ci), ("merged PRs", mp),
        ):
            if val >= GH_LIMIT:
                cap_hits.append(f"{repo} {name}")
        totals["open_issues"] += oi
        totals["open_prs"] += op
        totals["closed"] += ci
        totals["merged"] += mp
        totals["ready"] += ready
        totals["scoping"] += scoping
        lines.append(
            f"| {repo:<15} | {oi:<11} | {op:<8} | {ci:<13} | "
            f"{mp:<10} | {ready:<11} | {scoping:<13} |"
        )
    lines.append(
        f"| **Total**       | **{totals['open_issues']}** | "
        f"**{totals['open_prs']}** | **{totals['closed']}** | "
        f"**{totals['merged']}** | **{totals['ready']}** | "
        f"**{totals['scoping']}** |"
    )
    if cap_hits:
        lines.append("")
        lines.append(
            f"WARN: cap hit on: {', '.join(cap_hits)} -- raise `GH_LIMIT`."
        )
    lines.append("")

    in_flight: list[tuple[str, int, str, str, str, str]] = []
    for r in results:
        if "error" in r:
            continue
        repo = r["repo"]
        labeled = {
            i["number"]: i
            for i in r["open_issues"]
            if "agent-in-progress" in labels_of(i)
        }
        branched: dict[int, dict] = {}
        for pr in r["open_prs"]:
            m = BRANCH_RE.match(pr["headRefName"])
            if m:
                branched[int(m.group(2))] = pr
        for num in sorted(set(labeled) | set(branched)):
            issue = labeled.get(num)
            pr = branched.get(num)
            signal = {
                (True, True): "label+branch",
                (True, False): "label only",
                (False, True): "branch only",
            }[(num in labeled, num in branched)]
            title = (issue or pr)["title"]
            url = (issue or pr)["url"]
            pr_num = f"#{pr['number']}" if pr else "--"
            in_flight.append((repo, num, pr_num, signal, title, url))

    if in_flight:
        lines.append(f"In-flight agents ({len(in_flight)}):")
        lines.append("")
        lines.append("| Repo            | Issue | PR   | Signal       | Title |")
        lines.append("|-----------------|-------|------|--------------|-------|")
        for repo, num, pr_num, signal, title, _url in in_flight:
            lines.append(
                f"| {repo:<15} | #{num} | {pr_num} | {signal:<12} | {title} |"
            )
    else:
        lines.append("No agents currently in flight.")
    lines.append("")

    thin = [
        r for r in results
        if "error" not in r
        and sum(1 for i in r["open_issues"] if "ready-for-agent" in labels_of(i))
        < SCOPING_SURFACE_THRESHOLD
    ]
    if thin:
        candidates: list[tuple[str, dict, str]] = []
        for r in thin:
            pick = pick_scoping_candidate(r["open_issues"])
            if pick is not None:
                issue, source = pick
                candidates.append((r["repo"], issue, source))
        if candidates:
            lines.append(
                f"Next to scope (ready queue thin on {len(thin)} repo(s); "
                "oldest candidate per repo):"
            )
            lines.append("")
            for repo, issue, source in candidates:
                created = datetime.fromisoformat(
                    issue["createdAt"].replace("Z", "+00:00")
                ).astimezone(timezone.utc)
                age = humanize_age(created, now)
                tag = "needs-scoping" if source == "labeled" else "unlabeled"
                lines.append(
                    f"- [{repo}#{issue['number']}]({issue['url']}) -- "
                    f"{issue['title']}  _(age {age}, {tag})_"
                )
            lines.append("")
            lines.append(
                "_To scope: open the issue, pick an option / add acceptance "
                "criteria, then add `ready-for-agent` (and remove "
                "`needs-scoping` if present)._"
            )
        else:
            thin_names = ", ".join(r["repo"] for r in thin)
            lines.append(
                f"Ready queue thin on: {thin_names} -- no scoping candidates "
                "found (issues may be backlog-tagged or terminal-labeled)."
            )
    lines.append("")
    lines.extend(render_metrics(metrics))
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str]) -> int:
    since, is_first_run = read_state()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=METRIC_WINDOW_DAYS)
    try:
        results = fetch_all(iso_z(since), iso_z(window_start))
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    metrics = compute_metrics(results, now)
    print(render(results, since, is_first_run, now, metrics), end="")

    if any("error" not in r for r in results):
        write_state(now)
        write_snapshot(results, now, since)
    else:
        print(
            "WARN: all repos failed; state.json not updated.", file=sys.stderr
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
