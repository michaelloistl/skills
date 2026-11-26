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
            "~/.claude-on/skills/drive-spec/drive-spec answered --help 2>&1 | head -20",
            "./drive-spec ask -h | sed -n 1,5p",
            "git log | tail",
            "python3 - <<'PY'\ns = 'run `drive-spec verify` and quote it'\nPY\nrg -n \"a|b\" x",
            'git commit -m "Run drive-spec open bare, not | tail"',
            "python3 - <<'PY'\nedit('STATUS.md', '| `review` | `drive-spec frontier` as it stops |', 'x')\nPY",
            'ps -eo pid,args | grep -E "rails|drive-spec verify|minitest" | grep -v grep | head',
            "ps aux | grep -v grep | grep -E '(drive-spec verify|bin/rails test)' | head -5",
        ):
            self.assertFalse(denied(command), command)


if __name__ == "__main__":
    unittest.main()
