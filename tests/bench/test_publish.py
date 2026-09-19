# ABOUTME: Tests for the publish service — refusals happen before the uploader is ever called.
# ABOUTME: The uploader is a fake that records calls; nothing here touches Cloudflare.

from __future__ import annotations

from pathlib import Path

import pytest

from oversteward.bench.publish import RefusedError, publish
from oversteward.bench.wrangler import Deployment, UploadError
from tests.bench.test_checks import INDEXABLE_PAGE, NOINDEX_PAGE, _bench


class FakeUploader:
    def __init__(self, deployment: Deployment | None = None, error: Exception | None = None):
        self.calls: list[tuple[Path, str]] = []
        self.deployment = deployment or Deployment(
            url="https://abc123.ab-aigranthelper.pages.dev", alias="https://smoke.ab-aigranthelper.pages.dev"
        )
        self.error = error

    def __call__(self, directory: Path, branch: str) -> Deployment:
        self.calls.append((directory, branch))
        if self.error:
            raise self.error
        return self.deployment


class TestRefusal:
    def test_an_indexable_page_refuses_before_anything_uploads(self, tmp_path):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE, "b.html": INDEXABLE_PAGE})
        upload = FakeUploader()
        with pytest.raises(RefusedError) as info:
            publish(bench, branch="smoke", upload=upload)
        assert upload.calls == []
        assert "b.html" in str(info.value)

    def test_a_missing_headers_file_refuses_before_anything_uploads(self, tmp_path):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE})
        (bench / "_headers").unlink()
        upload = FakeUploader()
        with pytest.raises(RefusedError, match="_headers is missing"):
            publish(bench, branch="smoke", upload=upload)
        assert upload.calls == []

    def test_a_missing_robots_txt_refuses_before_anything_uploads(self, tmp_path):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE})
        (bench / "robots.txt").unlink()
        upload = FakeUploader()
        with pytest.raises(RefusedError, match="robots.txt is missing"):
            publish(bench, branch="smoke", upload=upload)
        assert upload.calls == []

    def test_the_refusal_lists_every_reason(self, tmp_path):
        bench = _bench(tmp_path, **{"a.html": INDEXABLE_PAGE})
        (bench / "_headers").unlink()
        with pytest.raises(RefusedError) as info:
            publish(bench, branch="smoke", upload=FakeUploader())
        assert info.value.reasons == (
            "a.html lacks <meta name=\"robots\" content=\"noindex\">",
            "_headers is missing",
        )


class TestPublish:
    def test_a_clean_directory_is_uploaded_once_to_the_named_branch(self, tmp_path):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE, "v2/index.html": NOINDEX_PAGE})
        upload = FakeUploader()
        report = publish(bench, branch="smoke-2026-09-19", upload=upload)
        assert upload.calls == [(bench, "smoke-2026-09-19")]
        assert report.deployment.url == "https://abc123.ab-aigranthelper.pages.dev"

    def test_page_urls_hang_off_the_branch_alias_when_there_is_one(self, tmp_path):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE, "v2/index.html": NOINDEX_PAGE, "v3.html": NOINDEX_PAGE})
        report = publish(bench, branch="smoke", upload=FakeUploader())
        assert report.page_urls == (
            "https://smoke.ab-aigranthelper.pages.dev/",
            "https://smoke.ab-aigranthelper.pages.dev/v2/",
            "https://smoke.ab-aigranthelper.pages.dev/v3",
        )

    def test_page_urls_fall_back_to_the_deployment_url_without_an_alias(self, tmp_path):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE})
        upload = FakeUploader(Deployment(url="https://abc123.ab-aigranthelper.pages.dev", alias=None))
        report = publish(bench, branch="smoke", upload=upload)
        assert report.page_urls == ("https://abc123.ab-aigranthelper.pages.dev/",)

    def test_an_upload_failure_propagates(self, tmp_path):
        bench = _bench(tmp_path, **{"index.html": NOINDEX_PAGE})
        with pytest.raises(UploadError, match="exited 1"):
            publish(bench, branch="smoke", upload=FakeUploader(error=UploadError("wrangler exited 1: nope")))
