"""The ``rm -rf /.*`` row reads past a plain ``rm`` of scratch entries only.

Recorded false positives: ``rm -rf /tmp/<name> && mkdir -p /tmp/<name> && ...`` was
refused as "recursive force-deletion rooted at the filesystem root".
"""

from __future__ import annotations

import os
import sys

import pytest

from kiro_crew.security import is_denied

ALLOWED = [
    "rm -rf /tmp/f2-base && mkdir -p /tmp/f2-base",
    "git fetch -q origin main && rm -rf /tmp/pwt-wt; git worktree add -q /tmp/pwt-wt",
    "uname -m; rm -rf /tmp/iioff 2>/dev/null; ls",
    "rm -rf /tmp/a /var/tmp/b/c",
    'B="$(rm -rf /tmp/x)"; echo ok',
]

DENIED = [
    "rm -rf /",
    "rm -rf /tmp/x; rm -rf /",
    "rm -rf /tmp/x /etc",
    "rm -rf /etc",
    "rm -rf /tmp",
    "rm -rf /tmp/",
    "rm -rf /tmp/*",
    "rm -rf /tmp/x/",
    "rm -rf /tmp/../etc",
    "rm -rf /tmp/./x",
    "rm -rf /tmp/$X",
    "rm -rf '/tmp/x' /usr",
    "sudo rm -rf /tmp/x",
    'bash -c "rm -rf /tmp/x; rm -rf /usr"',
    "rm -rf /tmp/x && echo rm -rf /usr | sh",
    "/bin/rm -rf /tmp/x /usr",
]


@pytest.mark.parametrize("command", ALLOWED)
def test_scratch_rm_is_allowed(command: str) -> None:
    assert is_denied(command) is None


@pytest.mark.parametrize("command", DENIED)
def test_root_or_unproven_rm_stays_denied(command: str) -> None:
    assert is_denied(command) is not None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX /tmp symlink to the root")
def test_scratch_entry_through_a_symlinked_folder_stays_denied() -> None:
    link = f"/tmp/kc-rm-view-{os.getpid()}"
    os.symlink("/", link)
    try:
        assert is_denied(f"rm -rf {link}/etc") is not None
        # the link itself is removed, not followed
        assert is_denied(f"rm -rf {link}") is None
    finally:
        os.unlink(link)
