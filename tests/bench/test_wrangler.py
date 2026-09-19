# ABOUTME: Tests for the wrangler connector — argv shape, credentials only in the child's environment,
# ABOUTME: URL parsing from wrangler's own completion lines, and a non-zero exit that never echoes the token.

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from oversteward.bench.config import PagesCredentials
from oversteward.bench.wrangler import DEFAULT_WRANGLER, Deployment, UploadError, deploy

CREDS = PagesCredentials(token="tok-secret", account_id="acct-1", project="ab-aigranthelper")

SUCCESS = (
    "🌍  Uploading... (3/3)\n✨ Success! Uploaded 3 files (1.02 sec)\n\n✨ Uploading _headers\n"
    "🌎 Deploying...\n✨ Deployment complete! Take a peek over at https://1a2b3c4d.ab-aigranthelper.pages.dev\n"
    "✨ Deployment alias URL: https://smoke-2026-09-19.ab-aigranthelper.pages.dev\n"
)


#: wrangler 4.135.0's stderr for a rejected request, captured verbatim (bogus credentials, nothing published).
REAL_FAILURE = (
    "\x1b[31m✘ \x1b[41;31m[\x1b[41;97mERROR\x1b[41;31m]\x1b[0m \x1b[1mA request to the Cloudflare API "
    "(/accounts/bogus/pages/projects/ab-aigranthelper) failed.\x1b[0m\n"
    "\n"
    "  Could not route to /client/v4/accounts/bogus/pages/projects/ab-aigranthelper, perhaps your object "
    "identifier is invalid? [code: 7003]\n"
    "  \n"
    "  If you think this is a bug, please open an issue at: "
    "\x1b[4mhttps://github.com/cloudflare/workers-sdk/issues/new/choose\x1b[0m\n"
    "\n"
    "\n"
    "🪵  Logs were written to \"/home/natha/.config/.wrangler/logs/wrangler-2026-09-19_03-46-32_899.log\"\n"
)


class FakeRun:
    def __init__(self, returncode: int = 0, stdout: str = SUCCESS, stderr: str = "", raise_: Exception | None = None):
        self.calls: list[dict] = []
        self.completed = subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)
        self.raise_ = raise_

    def __call__(self, command, **kwargs):
        self.calls.append({"command": list(command), **kwargs})
        if self.raise_:
            raise self.raise_
        return self.completed


class TestCommand:
    def test_deploys_the_directory_to_the_project_and_branch(self, tmp_path):
        run = FakeRun()
        deploy(tmp_path, credentials=CREDS, branch="smoke", run=run)
        command = run.calls[0]["command"]
        assert command[: len(DEFAULT_WRANGLER)] == list(DEFAULT_WRANGLER)
        assert command[len(DEFAULT_WRANGLER):] == [
            "pages", "deploy", str(tmp_path),
            "--project-name", "ab-aigranthelper", "--branch", "smoke", "--commit-dirty=true",
        ]

    def test_the_token_travels_in_the_environment_never_argv(self, tmp_path):
        run = FakeRun()
        deploy(tmp_path, credentials=CREDS, branch="smoke", run=run)
        call = run.calls[0]
        assert "tok-secret" not in " ".join(call["command"])
        assert call["env"]["CLOUDFLARE_API_TOKEN"] == "tok-secret"
        assert call["env"]["CLOUDFLARE_ACCOUNT_ID"] == "acct-1"
        assert call["env"]["WRANGLER_SEND_METRICS"] == "false"

    def test_runs_outside_the_deployed_directory_so_wrangler_cache_never_lands_in_it(self, tmp_path):
        run = FakeRun()
        deploy(tmp_path, credentials=CREDS, branch="smoke", run=run)
        cwd = Path(run.calls[0]["cwd"])
        assert cwd != tmp_path
        assert tmp_path not in cwd.parents and cwd not in tmp_path.parents

    def test_a_relative_directory_is_handed_to_wrangler_absolute(self, tmp_path, monkeypatch):
        """The child runs from a scratch cwd, so a path relative to the caller's cwd would not exist there."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "renders").mkdir()
        run = FakeRun()
        deploy(Path("renders"), credentials=CREDS, branch="smoke", run=run)
        command = run.calls[0]["command"]
        handed = Path(command[command.index("deploy") + 1])
        assert handed.is_absolute()
        assert handed == (tmp_path / "renders").resolve()

    def test_never_runs_through_a_shell(self, tmp_path):
        run = FakeRun()
        deploy(tmp_path, credentials=CREDS, branch="smoke", run=run)
        assert not run.calls[0].get("shell")


class TestResult:
    def test_reads_the_deployment_url_and_the_alias(self, tmp_path):
        assert deploy(tmp_path, credentials=CREDS, branch="smoke", run=FakeRun()) == Deployment(
            url="https://1a2b3c4d.ab-aigranthelper.pages.dev",
            alias="https://smoke-2026-09-19.ab-aigranthelper.pages.dev",
        )

    def test_a_deployment_without_an_alias_has_none(self, tmp_path):
        stdout = "✨ Deployment complete! Take a peek over at https://1a2b3c4d.ab-aigranthelper.pages.dev\n"
        assert deploy(tmp_path, credentials=CREDS, branch="smoke", run=FakeRun(stdout=stdout)).alias is None

    def test_exit_0_without_a_deployment_url_is_an_upload_error(self, tmp_path):
        stdout = "✨ Deployment complete! However, we couldn't ascertain the final status of your deployment.\n"
        with pytest.raises(UploadError, match="no deployment URL"):
            deploy(tmp_path, credentials=CREDS, branch="smoke", run=FakeRun(stdout=stdout))

    def test_a_non_zero_exit_is_an_upload_error_carrying_wranglers_error_line(self, tmp_path):
        """The fixture is wrangler 4.135's real stderr: ANSI-coloured [ERROR] line, detail, then the log trailer."""
        with pytest.raises(UploadError, match=r"exited 1: .*") as info:
            deploy(tmp_path, credentials=CREDS, branch="smoke", run=FakeRun(returncode=1, stdout="", stderr=REAL_FAILURE))
        message = str(info.value)
        assert "[ERROR] A request to the Cloudflare API (/accounts/bogus/pages/projects/ab-aigranthelper) failed." in message
        assert "[code: 7003]" in message
        assert "Logs were written" not in message
        assert "\x1b[" not in message

    def test_a_failure_without_an_error_line_carries_the_last_line_that_is_not_the_log_trailer(self, tmp_path):
        stderr = "something odd happened\n\n🪵  Logs were written to \"/home/x/.wrangler/logs/w.log\"\n"
        with pytest.raises(UploadError, match="exited 1: something odd happened$"):
            deploy(tmp_path, credentials=CREDS, branch="smoke", run=FakeRun(returncode=1, stdout="", stderr=stderr))

    def test_a_failure_message_never_carries_the_token(self, tmp_path):
        run = FakeRun(returncode=1, stdout="", stderr="boom\n")
        with pytest.raises(UploadError) as info:
            deploy(tmp_path, credentials=CREDS, branch="smoke", run=run)
        assert "tok-secret" not in str(info.value)

    def test_a_missing_npx_is_an_upload_error(self, tmp_path):
        run = FakeRun(raise_=FileNotFoundError("npx"))
        with pytest.raises(UploadError, match="not found on PATH"):
            deploy(tmp_path, credentials=CREDS, branch="smoke", run=run)

    def test_a_timeout_is_an_upload_error(self, tmp_path):
        run = FakeRun(raise_=subprocess.TimeoutExpired("npx", 1))
        with pytest.raises(UploadError, match="did not finish"):
            deploy(tmp_path, credentials=CREDS, branch="smoke", run=run)
