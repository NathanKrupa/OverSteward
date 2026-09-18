# ABOUTME: Drives the node test suite for cards.js from pytest so one gate covers the page script.
# ABOUTME: A missing node is a failure, never a skip — a skip would read as a pass on the script.

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

SUITE = Path(__file__).with_name("cards.test.cjs")


def test_the_page_script_passes_its_node_suite():
    node = shutil.which("node")
    assert node, "node is required to test cards.js — install it or the page script goes untested"

    result = subprocess.run(
        [node, "--test", "--test-reporter=tap", str(SUITE)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "# fail 0" in result.stdout, result.stdout
    # node counts the file itself as a passing test when it holds none: the
    # pass count must equal the number of tests the suite declares.
    declared = SUITE.read_text(encoding="utf-8").count("\ntest(")
    assert declared > 0
    assert f"# pass {declared}\n" in result.stdout, result.stdout
