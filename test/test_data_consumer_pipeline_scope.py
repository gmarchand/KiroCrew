"""The data-consumer exemption is withdrawn per pipeline, not per command line.

Recorded false positive: ``rm -rf $T/ref/*; ...; grep -rln x tmpl | xargs sed -i ...``
-- the later ``| xargs`` withdrew the exemption from the earlier ``rm`` too, so its
glob read as a possible ``pkill`` and a product path in the line read as its target.
An escaped backtick in a double-quoted sed script also opened a fake substitution.
"""

from __future__ import annotations

import pytest

from kiro_crew.security import is_denied

ALLOWED = [
    "rm -f /tmp/ref/*; cp -r /kirocrew/venv/jinja2 /tmp/ref; grep -rl x . | xargs sed -i s/a/b/g",
    'sed -i "s|x|fire \\`kirocrew-dashboard\\`, which|" a.ts && git diff a.ts',
    # recorded block, verbatim (sed edits of two test files)
    "sed -i \"s| \\* does is replace the field bag and post a message, which the page's existing"
    " script| * does is replace the field bag and fire \\`kirocrew-dashboard\\`, which the page's"
    ' script|" src/test/projectReportPage.test.ts && sed -i "s|/\\*\\* A host push: the page\'s own'
    " message listener re-renders on the next tick. \\*/|/** A host push: the page's"
    ' \\`kirocrew-dashboard\\` listener re-renders on the next tick. */|"'
    " src/test/orgChartFoldPage.test.ts && git diff src/test",
]

DENIED = [
    "echo pkill -f kirocrew | sh",
    "echo pkill -f kirocrew | xargs",
    "printf 'pkill -f kirocrew' | bash; ls",
    "ls; echo kirocrew token | sh",
    "rm -rf /work/*; pkill -f kirocrew",
    "echo x | sed 's/.*/pkill -f kirocrew/e'",
    'echo "`pkill -f kirocrew`"',
    'bash -c "echo \\`pkill -f kirocrew\\`"',
]


@pytest.mark.parametrize("command", ALLOWED)
def test_unrelated_pipeline_does_not_withdraw_the_exemption(command: str) -> None:
    assert is_denied(command) is None


@pytest.mark.parametrize("command", DENIED)
def test_pipeline_into_an_evaluator_stays_denied(command: str) -> None:
    assert is_denied(command) is not None
