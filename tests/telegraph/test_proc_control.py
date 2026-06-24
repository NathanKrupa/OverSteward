# ABOUTME: Tests for the POSIX/proc ProcessControl inner connector (the eviction OS edge).
# ABOUTME: Verifies the /proc/<pid>/stat parser including comm tokens containing spaces and ).

from __future__ import annotations

import os

from oversteward.telegraph.proc_control import PosixProcessControl


def test_stat_parser_extracts_comm_and_ppid():
    # Real kernel stat line: pid (comm) state ppid pgrp ...
    raw = "1234 (claude) S 1000 1234 1234 0 -1 ..."
    comm, ppid = PosixProcessControl._parse_stat(raw)
    assert comm == "claude"
    assert ppid == "1000"


def test_stat_parser_handles_comm_with_spaces_and_paren():
    raw = "42 (weird )name) S 7 42 42 ..."
    comm, ppid = PosixProcessControl._parse_stat(raw)
    assert comm == "weird )name"
    assert ppid == "7"


def test_poll_alive_true_for_self():
    proc = PosixProcessControl()
    assert proc.poll_alive(os.getpid()) is True


def test_proc_info_of_self_matches_os_getppid():
    proc = PosixProcessControl()
    info = proc.proc_info(os.getpid())
    assert info is not None
    assert info.ppid == os.getppid()
    assert isinstance(info.name, str)


def test_proc_info_absent_pid_is_none():
    proc = PosixProcessControl()
    assert proc.proc_info(2**30) is None


def test_poll_alive_false_for_absent_pid():
    proc = PosixProcessControl()
    # PID 2**30 is effectively never live.
    assert proc.poll_alive(2**30) is False
