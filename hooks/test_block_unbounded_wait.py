"""Tests for block-unbounded-wait.sh. Run: python3 -m unittest discover -s hooks"""

import json
import subprocess
import unittest
from pathlib import Path

HOOK = Path(__file__).with_name("block-unbounded-wait.sh")


def denied(command):
    out = subprocess.run([str(HOOK)], input=json.dumps({"tool_input": {"command": command}}), capture_output=True,
                         text=True, check=True).stdout
    return bool(out) and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


class BlockUnboundedWait(unittest.TestCase):
    def test_denies_an_unbounded_sleep_loop(self):
        for command in (
            "until [ -s /tmp/x.output ]; do sleep 5; done; cat /tmp/x.output",
            "cd x; sed -n 1,8p y; until [ -s f ]; do sleep 5; done; cat f",
            "while true; do sleep 1; done",
            "while\ttrue; do sleep 1; done",
            "bash -c 'while :; do sleep 1; done'",
            'sh -c "set -e; until test -f f; do sleep 2; done"',
            "x=$(until curl -s localhost; do sleep 2; done)",
            "if a; then while b; do sleep 1; done; fi",
            "make &\nwhile pgrep make; do sleep 1; done",
        ):
            self.assertTrue(denied(command), command)

    def test_allows_bounded_loops_and_loop_words_in_text(self):
        for command in (
            "timeout 600 sh -c 'until [ -s f ]; do sleep 5; done'",
            "timeout -k 5 60 bash -c 'while true; do sleep 1; done'",
            "python3 count.py 'This polls in a while/until loop with sleep and no time bound'",
            'git commit -m "Wait until ready, then sleep less"',
            "sleep 5",
            "for i in 1 2 3; do sleep 1; done",
        ):
            self.assertFalse(denied(command), command)
