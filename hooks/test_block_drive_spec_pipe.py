"""Tests for block-drive-spec-pipe.py. Run: python3 -m unittest discover -s hooks"""

import json
import subprocess
import unittest
from pathlib import Path

HOOK = Path(__file__).with_name("block-drive-spec-pipe.py")


def denied(command):
    out = subprocess.run([str(HOOK)], input=json.dumps({"tool_input": {"command": command}}), capture_output=True,
                         text=True, check=True).stdout
    return bool(out) and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


class BlockDriveSpecPipe(unittest.TestCase):
    def test_denies_piping_the_output(self):
        for command in (
            "D=/x/drive-spec/drive-spec; $D open 3035 --base develop 2>&1 | tail -15 && $D preview 3035",
            '/x/drive-spec confirm 3035 2>&1 | tail -5; echo "exit ${pipestatus[1]}"',
            "D=/x/drive-spec; ${D} frontier 10 |& tee x",
            "./drive-spec plan 10 --json | jq .slices",
        ):
            self.assertTrue(denied(command), command)

    def test_allows_stdin_and_plain_runs(self):
        for command in (
            'echo "Deviations: none" | /x/drive-spec integrate 3035 3036 --deviations -',
            "cat <<EOF | $D reviewed 3035 --left -\n- a | b\nEOF",
            'D=/x/drive-spec; $D halt 10 11 "gate | red"',
            "D=/x/drive-spec; $D plan 10 --json || echo failed",
            "drive-spec --help | head",
            "git log | tail",
        ):
            self.assertFalse(denied(command), command)


if __name__ == "__main__":
    unittest.main()
