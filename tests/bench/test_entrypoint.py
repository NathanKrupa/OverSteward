# ABOUTME: Tests for scripts/design_bench.py — exit codes and output, with the uploader and environment injected.
# ABOUTME: 0 published / manifest written; 1 refused or upload failed; 2 credentials unset. Never a traceback.

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

from oversteward.bench.config import ACCOUNT_VAR, TOKEN_VAR
from oversteward.bench.wrangler import UploadError
from oversteward.judge.models import manifest_from_mapping
from tests.bench.test_checks import INDEXABLE_PAGE, NOINDEX_PAGE, _bench
from tests.bench.test_publish import FakeUploader

REPO_ROOT = Path(__file__).resolve().parents[2]
FULL = {TOKEN_VAR: "tok-secret", ACCOUNT_VAR: "acct-1"}


def _module():
    spec = importlib.util.spec_from_file_location("design_bench", REPO_ROOT / "scripts" / "design_bench.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Factory:
    """Stands in for the wrangler connector: hands back one FakeUploader and remembers being asked."""

    def __init__(self, uploader: FakeUploader | None = None):
        self.uploader = uploader or FakeUploader()
        self.asked = 0

    def __call__(self, credentials):
        self.asked += 1
        return self.uploader


class TestPublish:
    def test_missing_credentials_exit_2_before_the_uploader_is_built(self, tmp_path, capsys):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE})
        factory = _Factory()
        code = _module().main(["publish", str(bench)], env={}, dotenv_path=tmp_path / "absent", uploader=factory)
        assert code == 2
        err = capsys.readouterr().err
        assert TOKEN_VAR in err
        assert "Traceback" not in err
        assert factory.asked == 0

    def test_a_refusal_exits_1_lists_every_reason_and_uploads_nothing(self, tmp_path, capsys):
        bench = _bench(tmp_path, **{"index.html": INDEXABLE_PAGE})
        (bench / "_headers").unlink()
        factory = _Factory()
        code = _module().main(["publish", str(bench)], env=FULL, dotenv_path=tmp_path / "absent", uploader=factory)
        assert code == 1
        err = capsys.readouterr().err
        assert "index.html lacks" in err
        assert "_headers is missing" in err
        assert "Traceback" not in err
        assert factory.uploader.calls == []

    def test_an_upload_failure_exits_1(self, tmp_path, capsys):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE})
        factory = _Factory(FakeUploader(error=UploadError("wrangler exited 1: Authentication error")))
        code = _module().main(["publish", str(bench)], env=FULL, dotenv_path=tmp_path / "absent", uploader=factory)
        assert code == 1
        err = capsys.readouterr().err
        assert "Authentication error" in err
        assert "Traceback" not in err

    def test_a_publish_exits_0_and_prints_every_url(self, tmp_path, capsys):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE, "v2/index.html": NOINDEX_PAGE})
        factory = _Factory()
        code = _module().main(
            ["publish", str(bench), "--branch", "smoke-2026-09-19"],
            env=FULL, dotenv_path=tmp_path / "absent", uploader=factory,
        )
        assert code == 0
        assert factory.uploader.calls == [(bench, "smoke-2026-09-19")]
        out = capsys.readouterr().out
        assert "https://abc123.ab-aigranthelper.pages.dev" in out
        assert "https://smoke.ab-aigranthelper.pages.dev/v2/" in out

    def test_the_branch_defaults_to_the_directory_name(self, tmp_path):
        bench = _bench(tmp_path / "Round One", **{"index.html": NOINDEX_PAGE})
        factory = _Factory()
        assert _module().main(["publish", str(bench)], env=FULL, dotenv_path=tmp_path / "absent", uploader=factory) == 0
        assert factory.uploader.calls[0][1] == "round-one"

    def test_a_missing_directory_exits_1(self, tmp_path, capsys):
        factory = _Factory()
        code = _module().main(["publish", str(tmp_path / "absent")], env=FULL, dotenv_path=tmp_path / "absent", uploader=factory)
        assert code == 1
        assert "Traceback" not in capsys.readouterr().err
        assert factory.uploader.calls == []


class TestManifest:
    def test_a_directory_source_writes_a_manifest_the_judge_can_read(self, tmp_path, capsys):
        bench = _bench(tmp_path / "bench", **{"v1/index.html": NOINDEX_PAGE, "v2/index.html": NOINDEX_PAGE, "v3/index.html": NOINDEX_PAGE})
        out_dir = tmp_path / "manifests"
        code = _module().main([
            "manifest", str(bench), "--page-type", "foundation", "--pairs", "all",
            "--base-url", "https://smoke.ab-aigranthelper.pages.dev", "--name", "round-1", "--out-dir", str(out_dir),
        ])
        assert code == 0
        written = out_dir / "round-1.yaml"
        assert str(written) in capsys.readouterr().out
        manifest = manifest_from_mapping(yaml.safe_load(written.read_text(encoding="utf-8")))
        assert manifest.page_types == {"foundation": (
            "https://smoke.ab-aigranthelper.pages.dev/v1/",
            "https://smoke.ab-aigranthelper.pages.dev/v2/",
            "https://smoke.ab-aigranthelper.pages.dev/v3/",
        )}
        assert len(manifest.pairs) == 3

    def test_a_url_listing_source_needs_no_base_url_and_pairs_default_to_none(self, tmp_path):
        listing = tmp_path / "urls.txt"
        listing.write_text("https://a/\nhttps://b/\n", encoding="utf-8")
        out_dir = tmp_path / "manifests"
        code = _module().main(["manifest", str(listing), "--page-type", "lead_page", "--name", "r", "--out-dir", str(out_dir)])
        assert code == 0
        manifest = manifest_from_mapping(yaml.safe_load((out_dir / "r.yaml").read_text(encoding="utf-8")))
        assert manifest.page_types == {"lead_page": ("https://a/", "https://b/")}
        assert manifest.pairs == ()

    def test_facts_are_written_relative_to_the_manifest(self, tmp_path):
        listing = tmp_path / "urls.txt"
        listing.write_text("https://a/\n", encoding="utf-8")
        out_dir = tmp_path / "manifests"
        facts = out_dir / "facts" / "f.json"
        facts.parent.mkdir(parents=True)
        facts.write_text("{}", encoding="utf-8")
        code = _module().main([
            "manifest", str(listing), "--page-type", "lead_page", "--name", "r", "--out-dir", str(out_dir), "--facts", str(facts),
        ])
        assert code == 0
        data = yaml.safe_load((out_dir / "r.yaml").read_text(encoding="utf-8"))
        assert data["ground_truth"] == {"https://a/": "facts/f.json"}

    def test_a_directory_source_without_base_url_exits_1(self, tmp_path, capsys):
        bench = _bench(tmp_path / "bench", **{"v1/index.html": NOINDEX_PAGE})
        code = _module().main(["manifest", str(bench), "--page-type", "foundation", "--name", "r", "--out-dir", str(tmp_path / "m")])
        assert code == 1
        err = capsys.readouterr().err
        assert "--base-url" in err
        assert "Traceback" not in err
        assert not (tmp_path / "m" / "r.yaml").exists()

    def test_an_existing_manifest_is_never_overwritten(self, tmp_path, capsys):
        listing = tmp_path / "urls.txt"
        listing.write_text("https://a/\n", encoding="utf-8")
        out_dir = tmp_path / "manifests"
        out_dir.mkdir()
        (out_dir / "r.yaml").write_text("name: keep\n", encoding="utf-8")
        code = _module().main(["manifest", str(listing), "--page-type", "lead_page", "--name", "r", "--out-dir", str(out_dir)])
        assert code == 1
        assert "already exists" in capsys.readouterr().err
        assert (out_dir / "r.yaml").read_text(encoding="utf-8") == "name: keep\n"

    def test_missing_facts_file_exits_1(self, tmp_path, capsys):
        listing = tmp_path / "urls.txt"
        listing.write_text("https://a/\n", encoding="utf-8")
        code = _module().main([
            "manifest", str(listing), "--page-type", "lead_page", "--name", "r",
            "--out-dir", str(tmp_path / "m"), "--facts", str(tmp_path / "nope.json"),
        ])
        assert code == 1
        assert "nope.json" in capsys.readouterr().err
