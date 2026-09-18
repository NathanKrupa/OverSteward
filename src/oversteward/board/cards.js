// ABOUTME: The Estate Board's decision cards — each tap is one ruling written to GitHub through the viewer's connector.
// ABOUTME: The ruling (rule) is pure and testable under node; the DOM wiring (wire) is the only part that touches a page.

/*
 * A ruling is one comment carrying the decision plus one state change, made
 * with the viewer's own GitHub connector. The page holds no state of its own:
 * it reads the issue before writing (labels may have moved since the board
 * was built), writes, then reads again and reports only what GitHub shows.
 *
 * Every comment carries an idempotency marker. A write that fails ambiguously
 * (the connector did not answer) is resolved by looking for that marker on the
 * issue rather than by writing again.
 */

const SERVER = "GitHub";
const TOOLS = { read: "issue_read", comment: "add_issue_comment", write: "issue_write" };
const NEEDS_INPUT = "needs-input";
const READY_FOR_AGENT = "ready-for-agent";

/* Errors on which the tool may still have run — the connector's own ruling. */
const AMBIGUOUS = new Set(["server_unavailable", "upstream_error", "cancelled", "rate_limited"]);

const VERBS = {
  // The exact form /answer posts, so a re-dispatched agent reads both alike.
  answer: {
    heading: "[answering @nathankrupa question]:",
    requires: "open",
    requiresLabel: NEEDS_INPUT,
    change: (issue) => ({
      labels: [...issue.labels.filter((l) => l !== NEEDS_INPUT), READY_FOR_AGENT],
    }),
    settled: (issue) =>
      issue.state === "open" &&
      !issue.labels.includes(NEEDS_INPUT) &&
      issue.labels.includes(READY_FOR_AGENT),
  },
  close: {
    heading: "[board ruling: closed — every child is closed]",
    requires: "open",
    change: () => ({ state: "closed", state_reason: "completed" }),
    settled: (issue) => issue.state === "closed",
  },
  shelve: {
    heading: "[board ruling: shelved]",
    requires: "open",
    change: () => ({ state: "closed", state_reason: "not_planned" }),
    settled: (issue) => issue.state === "closed",
  },
  reopen: {
    heading: "[board ruling: reopened]",
    requires: "closed",
    change: () => ({ state: "open" }),
    settled: (issue) => issue.state === "open",
  },
};

function fail(code, message, extra) {
  return Object.assign(new Error(message), { code }, extra || {});
}

/* Built by concatenation: an HTML comment opener written literally inside an
 * inline script changes how the HTML parser reads the rest of the script. */
function marker(verb, key) {
  return "<" + "!-- estate-board " + verb + " " + key + " --" + ">";
}

async function readIssue(mcp, target, options) {
  const result = await mcp.callTool(
    SERVER,
    TOOLS.read,
    { method: "get", owner: target.owner, repo: target.repo, issue_number: target.number },
    options,
  );
  const issue = result.payload;
  if (!issue || typeof issue.state !== "string" || !Array.isArray(issue.labels)) {
    throw fail("bad_payload", "GitHub answered in a shape this page does not understand.");
  }
  return issue;
}

async function findComment(mcp, target, text) {
  for (let page = 1; page <= 10; page += 1) {
    const result = await mcp.callTool(
      SERVER,
      TOOLS.read,
      {
        method: "get_comments",
        owner: target.owner,
        repo: target.repo,
        issue_number: target.number,
        perPage: 100,
        page,
      },
      { cache: false },
    );
    const comments = Array.isArray(result.payload) ? result.payload : [];
    const hit = comments.find((c) => typeof c.body === "string" && c.body.includes(text));
    if (hit) return hit;
    if (comments.length < 100) return null;
  }
  return null;
}

/**
 * Make one ruling. Resolves `{key, commentUrl}` once GitHub shows the change;
 * rejects with an error carrying `code` — the connector's codes pass through,
 * plus `note_required`, `already_settled`, `bad_payload` and `unconfirmed`.
 */
async function rule(mcp, request, deps) {
  const { owner, repo, number, verb, noteRequired } = request;
  const note = (request.note || "").trim();
  const spec = VERBS[verb];
  if (!spec) throw fail("bad_verb", `No such ruling: ${verb}`);
  if (noteRequired && !note) throw fail("note_required", "This ruling needs its reason on the record.");
  const target = { owner, repo, number };
  const uuid = (deps && deps.uuid) || (() => crypto.randomUUID());

  const before = await readIssue(mcp, target, { cache: false });
  if (before.state !== spec.requires) {
    throw fail("already_settled", `The issue is already ${before.state} on GitHub.`);
  }
  if (spec.requiresLabel && !before.labels.includes(spec.requiresLabel)) {
    throw fail("already_settled", `The issue no longer carries ${spec.requiresLabel} — it was answered elsewhere.`);
  }

  const key = uuid();
  const mark = marker(verb, key);
  const body = [spec.heading, note, mark].filter(Boolean).join("\n\n");
  const args = { owner, repo, issue_number: number };
  let comment;
  try {
    comment = (await mcp.callTool(SERVER, TOOLS.comment, { ...args, body })).payload;
  } catch (err) {
    if (!AMBIGUOUS.has(err && err.code)) throw err;
    comment = await findComment(mcp, target, mark);
    if (!comment) throw err;
  }

  try {
    await mcp.callTool(SERVER, TOOLS.write, { method: "update", ...args, ...spec.change(before) });
  } catch (err) {
    if (!AMBIGUOUS.has(err && err.code)) throw err;
  }

  const after = await readIssue(mcp, target, { cache: { refresh: true } });
  if (!spec.settled(after)) {
    throw fail("unconfirmed", "The ruling was sent but GitHub does not show it yet.", {
      commentUrl: comment && comment.html_url ? comment.html_url : null,
    });
  }
  return { key, commentUrl: comment && comment.html_url ? comment.html_url : null };
}

/* What to tell the viewer for each failure — and whether the card may be tapped again. */
function copyFor(err) {
  const code = (err && err.code) || "upstream_error";
  const message = (err && err.message) || "";
  switch (code) {
    case "note_required":
      return { text: message, again: true };
    case "already_settled":
      return { text: `${message} Rebuild the board to see the current queue.`, again: false };
    case "unconfirmed":
      return { text: `${message} Open the issue on GitHub before tapping again.`, again: false };
    case "needs_reauth":
      return { text: "GitHub's credentials have lapsed. Reconnect GitHub in claude.ai → Settings → Connectors, then tap again.", again: true };
    case "server_not_connected":
    case "selection_required":
      return { text: "No GitHub connector answers for this view. Add or choose GitHub in claude.ai → Settings → Connectors.", again: true };
    case "not_in_manifest":
      return { text: "This page was not allowed to use GitHub in this view. Allow it when claude.ai asks, then tap again.", again: true };
    case "blocked_by_policy":
    case "approval_required":
      return { text: "Organisation policy blocks this write from a page.", again: false };
    case "tool_error":
      if (/not accessible by integration/i.test(message)) {
        return {
          text: "GitHub refused the write: the connector can read but not write. Install the Claude GitHub App (github.com/apps/claude) on the account with these repositories, then tap again.",
          again: true,
        };
      }
      return { text: `GitHub reported: ${message}`, again: true };
    case "server_unavailable":
    case "upstream_error":
    case "rate_limited":
    case "cancelled":
      return { text: "GitHub did not answer, and nothing of this ruling was found on the issue. Tap again in a moment.", again: true };
    case "not_granted":
    case "capability_disabled":
    case "capability_removed":
      return { text: "This view cannot reach connectors. Open the board in claude.ai.", again: false };
    case "bad_payload":
      return { text: message, again: false };
    default:
      return { text: `Could not write to GitHub (${code}). ${message}`.trim(), again: true };
  }
}

/* Bind every card on the page. `use` is `window.claude.use`, resolved lazily at tap time. */
function wire(root, use) {
  for (const form of root.querySelectorAll("form.card")) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const li = form.closest("li");
      const button = form.querySelector("button");
      const status = form.querySelector(".status");
      const request = {
        owner: li.dataset.owner,
        repo: li.dataset.repo,
        number: Number(li.dataset.number),
        verb: button.dataset.verb,
        noteRequired: button.dataset.noteRequired === "1",
        note: form.querySelector("textarea").value,
      };
      form.classList.add("pending");
      for (const el of form.elements) el.disabled = true;
      status.textContent = "Pending — writing to GitHub…";
      const mcp = await use("mcp");
      if (!mcp) {
        status.textContent = copyFor({ code: "not_granted" }).text;
        form.classList.remove("pending");
        for (const el of form.elements) el.disabled = false;
        return;
      }
      try {
        const done = await rule(mcp, request);
        form.classList.remove("pending");
        form.classList.add("done");
        li.dataset.state = "done";
        status.textContent = "Done — on GitHub. ";
        if (done.commentUrl) {
          const a = document.createElement("a");
          a.href = done.commentUrl;
          a.textContent = "View the ruling";
          status.appendChild(a);
        }
      } catch (err) {
        const copy = copyFor(err);
        form.classList.remove("pending");
        form.classList.add("failed");
        status.textContent = copy.text + " ";
        if (err && err.commentUrl) {
          const a = document.createElement("a");
          a.href = err.commentUrl;
          a.textContent = "View the comment";
          status.appendChild(a);
        }
        if (copy.again) for (const el of form.elements) el.disabled = false;
      }
    });
  }
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { rule, copyFor, VERBS, SERVER, TOOLS, AMBIGUOUS, marker };
} else if (typeof document !== "undefined") {
  wire(document, (name) => (window.claude && window.claude.use ? window.claude.use(name) : Promise.resolve(null)));
}
