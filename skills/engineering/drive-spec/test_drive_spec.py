"""Tests for the drive-spec script. Run: PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skills/engineering/drive-spec"""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("drive-spec")
loader = importlib.machinery.SourceFileLoader("drive_spec", str(SCRIPT))
ds = importlib.util.module_from_spec(importlib.util.spec_from_loader("drive_spec", loader))
loader.exec_module(ds)


def issue(n, parent=None, blocked=(), state="open", labels=(), title=None, extra=""):
    body = f"## What\n\nSlice {n}.\n{extra}"
    if parent is not None:
        body += f"\n## Parent\n\n#{parent}\n"
    if blocked:
        body += "\n## Blocked by\n\n" + "\n".join(f"- #{b}" for b in blocked) + "\n"
    return {"number": n, "title": title or f"Slice {n}", "body": body, "state": state,
            "pull_request": None, "labels": list(labels)}


SPEC = {"number": 10, "title": "Export reports", "body": "## Problem\n\nNo export.\n", "state": "open"}


def plan(issues, heads=(), prs=(), **kw):
    return ds.build_plan(SPEC, issues, list(heads), list(prs), **kw)


def numbers(p):
    return [s["number"] for s in p["slices"]]


def states(p):
    return {s["number"]: s["state"] for s in p["slices"]}


class Parsing(unittest.TestCase):
    def test_parent_is_first_ref_in_its_section(self):
        body = "## What\n\nSee #99.\n\n## Parent\n\n#10 (and #11)\n\n## Blocked by\n\n#3\n"
        self.assertEqual(ds.parent_of(body), 10)

    def test_no_parent_section(self):
        self.assertIsNone(ds.parent_of("Mentions #10 but has no section."))

    def test_blockers_stop_at_next_heading(self):
        body = "## Blocked by\n\n- #3\n- #1\n\n## Notes\n\n#7\n"
        self.assertEqual(ds.blockers_of(body), [1, 3])

    def test_subheading_stays_in_section(self):
        body = "## Blocked by\n\n### Hard\n- #4\n"
        self.assertEqual(ds.blockers_of(body), [4])

    def test_crlf_bodies(self):
        self.assertEqual(ds.parent_of("## Parent\r\n\r\n#10\r\n"), 10)

    def test_heading_case_and_trailing_hashes(self):
        self.assertEqual(ds.blockers_of("## BLOCKED BY ##\n#5\n"), [5])

    def test_repo_slug(self):
        for url in ["git@github.com:acme/app.git", "https://github.com/acme/app.git/",
                    "http://local_proxy@127.0.0.1:1234/git/acme/app"]:
            self.assertEqual(ds.repo_slug(url + "\n"), "acme/app")


class Refusals(unittest.TestCase):
    def test_spec_with_a_parent(self):
        spec = dict(SPEC, body="## Parent\n\n#1\n")
        p = ds.build_plan(spec, [issue(11, parent=10)], [], [])
        self.assertIn("## Parent of its own (#1)", p["refuse"])

    def test_no_tracer_bullets(self):
        p = plan([issue(11, parent=12, extra="Related to #10.")])
        self.assertIn("no tracer-bullets", p["refuse"])

    def test_pull_request(self):
        p = ds.build_plan(dict(SPEC, pull_request={"url": "x"}), [], [], [])
        self.assertIn("pull request", p["refuse"])

    def test_cycle_names_only_its_members(self):
        p = plan([issue(11, 10, [12]), issue(12, 10, [11]), issue(13, 10, [12]), issue(14, 10)])
        self.assertEqual(p["cycle"], [11, 12])
        self.assertEqual(p["refuse"], "blockers form a cycle: #11, #12")

    def test_self_block_is_a_cycle(self):
        p = plan([issue(11, 10, [11])])
        self.assertEqual(p["cycle"], [11])


class Order(unittest.TestCase):
    def test_lowest_number_first_among_ready(self):
        p = plan([issue(14, 10), issue(12, 10, [14]), issue(13, 10), issue(11, 10, [13])])
        self.assertEqual(numbers(p), [13, 11, 14, 12])

    def test_closed_slices_take_part(self):
        p = plan([issue(12, 10, [11]), issue(11, 10, state="closed")])
        self.assertEqual(numbers(p), [11, 12])

    def test_blockers_outside_the_spec_are_ignored_but_listed(self):
        p = plan([issue(11, 10, [3])])
        self.assertEqual(p["slices"][0]["blockers"], [])
        self.assertEqual(p["slices"][0]["external_blockers"], [3])
        self.assertIn("outside the spec, ignored: #3 (for #11)", ds.render(p))

    def test_mention_without_parent_is_not_a_slice(self):
        p = plan([issue(11, 10), issue(12, extra="See #10.")])
        self.assertEqual(numbers(p), [11])

    def test_slice_of_a_spec_with_a_longer_number(self):
        p = plan([issue(11, 10), issue(12, 100)])
        self.assertEqual(numbers(p), [11])

    def test_sub_issue_without_parent_is_invisible(self):
        p = plan([issue(11, 10)], sub_issues=[11, 15])
        self.assertEqual(p["invisible"], [15])


class States(unittest.TestCase):
    HEADS = ["agent/local-spec-10-export-reports", "agent/issue-12-wire-route",
             "agent/issue-13-button", "agent/issue-11-serializer", "agent/issue-1-other"]
    PRS = [{"number": 40, "head": "agent/issue-12-wire-route"}]

    def test_precedence(self):
        p = plan([issue(11, 10, state="closed"), issue(12, 10), issue(13, 10), issue(14, 10)],
                 self.HEADS, self.PRS)
        self.assertEqual(states(p), {11: "closed", 12: "open-pr", 13: "in-flight", 14: "todo"})
        self.assertEqual(p["slices"][1]["pr"], 40)
        self.assertEqual(p["slices"][2]["branch"], "agent/issue-13-button")
        self.assertIsNone(p["slices"][0]["branch"])
        self.assertEqual(p["spec_branch"], "agent/local-spec-10-export-reports")

    def test_issue_number_prefix_does_not_collide(self):
        p = plan([issue(1, 10)], ["agent/issue-11-serializer"])
        self.assertEqual(states(p), {1: "todo"})

    def test_held_only_in_cloud(self):
        issues = [issue(11, 10, labels=["needs:desktop"]), issue(12, 10, state="closed", labels=["needs:desktop"])]
        self.assertEqual(states(plan(issues, held_label="needs:desktop", cloud=True)), {11: "held", 12: "closed"})
        self.assertEqual(states(plan(issues, held_label="needs:desktop", cloud=False)), {11: "todo", 12: "closed"})

    def test_two_spec_branches_fail(self):
        with self.assertRaises(ds.Failed):
            plan([issue(11, 10)], ["agent/local-spec-10-a", "agent/local-spec-10-b"])


class Cli(unittest.TestCase):
    """The script end to end, against fake `gh` and `git` on PATH."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "bin").mkdir()
        (self.tmp / "repo" / ".claude").mkdir(parents=True)
        (self.tmp / "repo" / ".claude" / "drive-spec.json").write_text(
            json.dumps({"localOnly": {"label": "needs:desktop", "proof": "x.md"}}))
        self.fake("git", """
            case "$*" in
              "remote get-url origin") echo git@github.com:acme/app.git ;;
              "rev-parse --show-toplevel") echo "$REPO" ;;
              "ls-remote --heads origin agent/*")
                printf 'a\\trefs/heads/agent/local-spec-10-export\\nb\\trefs/heads/agent/issue-12-route\\n' ;;
              *) echo "unexpected git $*" >&2; exit 1 ;;
            esac""")
        self.fake("gh", """
            case "$2" in
              repos/acme/app/issues/10) cat "$FIX/spec.json" ;;
              "--paginate")
                case "$3" in
                  repos/acme/app/issues\\?*) cat "$FIX/issues.jsonl" ;;
                  repos/acme/app/issues/10/sub_issues) echo '{"number":11}' ;;
                  repos/acme/app/pulls\\?state=open\\&base=agent/local-spec-10-export\\&*) echo '{"number":40,"head":"agent/issue-12-route"}' ;;
                  *) echo "unexpected gh $*" >&2; exit 1 ;;
                esac ;;
              *) echo "unexpected gh $*" >&2; exit 1 ;;
            esac""")
        (self.tmp / "spec.json").write_text(json.dumps(SPEC))
        rows = [issue(11, 10, labels=["needs:desktop"]), issue(12, 10, [11]), issue(13, 10, [12], state="closed"),
                issue(14), issue(15, 10, [12], title="Unrelated #10 mention? no: real slice")]
        (self.tmp / "issues.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    def fake(self, name, body):
        f = self.tmp / "bin" / name
        f.write_text("#!/bin/sh\n" + textwrap.dedent(body).strip() + "\n")
        f.chmod(0o755)

    def run_plan(self, *args, cloud="false"):
        env = dict(os.environ, PATH=f"{self.tmp / 'bin'}:{os.environ['PATH']}", FIX=str(self.tmp),
                   REPO=str(self.tmp / "repo"), CLAUDE_CODE_REMOTE=cloud)
        return subprocess.run([str(SCRIPT), "plan", *args], capture_output=True, text=True, env=env)

    def test_json(self):
        out = self.run_plan("#10", "--json", cloud="true")
        self.assertEqual(out.returncode, 0, out.stderr)
        p = json.loads(out.stdout)
        self.assertEqual(p["spec_branch"], "agent/local-spec-10-export")
        self.assertEqual([(s["number"], s["state"]) for s in p["slices"]],
                         [(11, "held"), (12, "open-pr"), (13, "closed"), (15, "todo")])

    def test_text(self):
        out = self.run_plan("10")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("#12  open-pr #40  Slice 12  after #11", out.stdout)
        self.assertIn("#11  todo", out.stdout)

    def test_refusal_exits_2(self):
        (self.tmp / "spec.json").write_text(json.dumps(dict(SPEC, body="## Parent\n\n#1\n")))
        out = self.run_plan("10")
        self.assertEqual(out.returncode, 2)
        self.assertIn("refuse: #10 has a ## Parent of its own", out.stdout)

    def test_tracker_failure_is_loud(self):
        self.fake("gh", "echo 'HTTP 401' >&2; exit 1")
        out = self.run_plan("10")
        self.assertEqual(out.returncode, 1)
        self.assertIn("HTTP 401", out.stderr)


if __name__ == "__main__":
    unittest.main()
