// ABOUTME: Tests for the Estate Board's rulings — the exact writes each verb makes and how each failure is handled.
// ABOUTME: Runs under `node --test` with a fake connector; pytest drives it so one gate covers both languages.

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const cards = require(path.join(__dirname, "..", "..", "src", "oversteward", "board", "cards.js"));

const TARGET = { owner: "NathanKrupa", repo: "grantspider", number: 7 };

/* A connector whose reads are scripted and whose writes are recorded. */
function fakeMcp({ issue, comments = [], failures = {} }) {
  const calls = [];
  let state = { ...issue, labels: [...issue.labels] };
  return {
    calls,
    current: () => state,
    async callTool(server, tool, input) {
      calls.push({ server, tool, input });
      const failure = failures[tool];
      if (failure && (failure.times === undefined || failure.times-- > 0)) {
        throw Object.assign(new Error(failure.message || "boom"), { code: failure.code });
      }
      if (tool === "issue_read" && input.method === "get") return { payload: { ...state, labels: [...state.labels] } };
      if (tool === "issue_read" && input.method === "get_comments") return { payload: comments };
      if (tool === "add_issue_comment") {
        const c = { id: 1, body: input.body, html_url: "https://github.com/x/y/issues/7#issuecomment-1" };
        comments.push(c);
        return { payload: c };
      }
      if (tool === "issue_write") {
        if (input.labels) state = { ...state, labels: [...input.labels] };
        if (input.state) state = { ...state, state: input.state };
        return { payload: { ...state } };
      }
      throw new Error(`unexpected tool ${tool}`);
    },
  };
}

const deps = { uuid: () => "k-1" };

test("answer: comments in /answer's form and swaps needs-input for ready-for-agent", async () => {
  const mcp = fakeMcp({ issue: { state: "open", labels: ["needs-input", "bug"] } });

  const done = await cards.rule(mcp, { ...TARGET, verb: "answer", note: "Use option B.", noteRequired: true }, deps);

  assert.deepEqual(mcp.calls.map((c) => c.tool), ["issue_read", "add_issue_comment", "issue_write", "issue_read"]);
  assert.ok(mcp.calls.every((c) => c.server === cards.SERVER));
  const comment = mcp.calls[1].input;
  assert.equal(comment.issue_number, 7);
  assert.ok(comment.body.startsWith("[answering @nathankrupa question]:\n\nUse option B."));
  assert.ok(comment.body.endsWith("<!-- estate-board answer k-1 -->"));
  assert.deepEqual(mcp.calls[2].input, {
    method: "update", owner: "NathanKrupa", repo: "grantspider", issue_number: 7, labels: ["bug", "ready-for-agent"],
  });
  assert.equal(done.commentUrl, "https://github.com/x/y/issues/7#issuecomment-1");
  assert.equal(done.key, "k-1");
});

test("answer: a blank note is refused before any call", async () => {
  const mcp = fakeMcp({ issue: { state: "open", labels: ["needs-input"] } });

  await assert.rejects(cards.rule(mcp, { ...TARGET, verb: "answer", note: "  ", noteRequired: true }, deps), { code: "note_required" });
  assert.equal(mcp.calls.length, 0);
});

test("answer: an issue that no longer carries needs-input is already settled — no write", async () => {
  const mcp = fakeMcp({ issue: { state: "open", labels: ["ready-for-agent"] } });

  await assert.rejects(cards.rule(mcp, { ...TARGET, verb: "answer", note: "x", noteRequired: true }, deps), { code: "already_settled" });
  assert.deepEqual(mcp.calls.map((c) => c.tool), ["issue_read"]);
});

test("close: comments and closes as completed; an empty note is allowed", async () => {
  const mcp = fakeMcp({ issue: { state: "open", labels: ["epic:x"] } });

  await cards.rule(mcp, { ...TARGET, verb: "close", note: "", noteRequired: false }, deps);

  assert.equal(mcp.calls[1].input.body, "[board ruling: closed — every child is closed]\n\n<!-- estate-board close k-1 -->");
  assert.deepEqual(mcp.calls[2].input, {
    method: "update", owner: "NathanKrupa", repo: "grantspider", issue_number: 7, state: "closed", state_reason: "completed",
  });
});

test("shelve: closes as not planned", async () => {
  const mcp = fakeMcp({ issue: { state: "open", labels: [] } });

  await cards.rule(mcp, { ...TARGET, verb: "shelve", note: "Superseded by the new crawler.", noteRequired: true }, deps);

  assert.equal(mcp.calls[2].input.state_reason, "not_planned");
  assert.ok(mcp.calls[1].input.body.includes("Superseded by the new crawler."));
});

test("reopen: requires a closed issue and reopens it", async () => {
  const mcp = fakeMcp({ issue: { state: "closed", labels: [] } });

  await cards.rule(mcp, { ...TARGET, verb: "reopen", note: "", noteRequired: false }, deps);
  assert.deepEqual(mcp.calls[2].input, {
    method: "update", owner: "NathanKrupa", repo: "grantspider", issue_number: 7, state: "open",
  });

  const open = fakeMcp({ issue: { state: "open", labels: [] } });
  await assert.rejects(cards.rule(open, { ...TARGET, verb: "reopen", note: "", noteRequired: false }, deps), { code: "already_settled" });
});

test("close on an already-closed issue is settled, not re-closed", async () => {
  const mcp = fakeMcp({ issue: { state: "closed", labels: [] } });

  await assert.rejects(cards.rule(mcp, { ...TARGET, verb: "close", note: "", noteRequired: false }, deps), { code: "already_settled" });
  assert.equal(mcp.calls.length, 1);
});

test("a ruling GitHub does not show afterwards is unconfirmed, never reported done", async () => {
  const mcp = fakeMcp({ issue: { state: "open", labels: ["needs-input"] } });
  // The label write ADDS instead of replacing: needs-input survives beside ready-for-agent.
  const write = mcp.callTool.bind(mcp);
  mcp.callTool = async (server, tool, input) => {
    if (tool === "issue_write") {
      mcp.calls.push({ server, tool, input });
      mcp.current().labels.push(...input.labels.filter((l) => !mcp.current().labels.includes(l)));
      return { payload: {} };
    }
    return write(server, tool, input);
  };

  await assert.rejects(cards.rule(mcp, { ...TARGET, verb: "answer", note: "x", noteRequired: true }, deps), (err) => {
    assert.equal(err.code, "unconfirmed");
    assert.equal(err.commentUrl, "https://github.com/x/y/issues/7#issuecomment-1");
    return true;
  });
});

test("an ambiguous comment failure is resolved by finding the marker, not by commenting again", async () => {
  const mcp = fakeMcp({
    issue: { state: "open", labels: ["needs-input"] },
    comments: [{ id: 9, body: "older\n\n<!-- estate-board answer k-1 -->", html_url: "https://github.com/x/y/issues/7#issuecomment-9" }],
    failures: { add_issue_comment: { code: "server_unavailable", times: 1 } },
  });

  const done = await cards.rule(mcp, { ...TARGET, verb: "answer", note: "x", noteRequired: true }, deps);

  assert.deepEqual(mcp.calls.map((c) => c.tool), ["issue_read", "add_issue_comment", "issue_read", "issue_write", "issue_read"]);
  assert.equal(mcp.calls[2].input.method, "get_comments");
  assert.equal(done.commentUrl, "https://github.com/x/y/issues/7#issuecomment-9");
});

test("an ambiguous comment failure with no marker on the issue is surfaced with its code and stops", async () => {
  const mcp = fakeMcp({
    issue: { state: "open", labels: ["needs-input"] },
    failures: { add_issue_comment: { code: "upstream_error" } },
  });

  await assert.rejects(cards.rule(mcp, { ...TARGET, verb: "answer", note: "x", noteRequired: true }, deps), { code: "upstream_error" });
  assert.deepEqual(mcp.calls.map((c) => c.tool), ["issue_read", "add_issue_comment", "issue_read"]);
});

test("a definite failure (GitHub 403) passes through with its code and makes no further write", async () => {
  const mcp = fakeMcp({
    issue: { state: "open", labels: ["needs-input"] },
    failures: { add_issue_comment: { code: "tool_error", message: "403 Resource not accessible by integration" } },
  });

  await assert.rejects(cards.rule(mcp, { ...TARGET, verb: "answer", note: "x", noteRequired: true }, deps), { code: "tool_error" });
  assert.deepEqual(mcp.calls.map((c) => c.tool), ["issue_read", "add_issue_comment"]);
});

test("an ambiguous state write is settled by the confirming read", async () => {
  const mcp = fakeMcp({
    issue: { state: "open", labels: [] },
    failures: { issue_write: { code: "server_unavailable" } },
  });
  // The write "failed" but GitHub applied it: the confirming read sees closed.
  const read = mcp.callTool.bind(mcp);
  let reads = 0;
  mcp.callTool = async (server, tool, input) => {
    if (tool === "issue_read" && input.method === "get" && ++reads === 2) {
      mcp.calls.push({ server, tool, input });
      return { payload: { state: "closed", labels: [] } };
    }
    return read(server, tool, input);
  };

  const done = await cards.rule(mcp, { ...TARGET, verb: "close", note: "", noteRequired: false }, deps);
  assert.equal(done.key, "k-1");
});

test("copy: each failure the viewer can fix names the fix and whether to tap again", () => {
  const forbidden = cards.copyFor({ code: "tool_error", message: "403 Resource not accessible by integration" });
  assert.match(forbidden.text, /github\.com\/apps\/claude/);
  assert.equal(forbidden.again, true);

  assert.match(cards.copyFor({ code: "needs_reauth" }).text, /Settings → Connectors/);
  assert.equal(cards.copyFor({ code: "already_settled", message: "x" }).again, false);
  assert.equal(cards.copyFor({ code: "unconfirmed", message: "x" }).again, false);
  assert.equal(cards.copyFor({ code: "not_granted" }).again, false);
  assert.match(cards.copyFor({ code: "server_unavailable" }).text, /Tap again/);
  assert.match(cards.copyFor({ code: "something_new", message: "m" }).text, /something_new/);
});
