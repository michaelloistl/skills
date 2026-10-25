"""Tests for the drive-spec script. Run: PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skills/engineering/drive-spec"""

import fcntl
import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import types
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


FAKE_GH = r"""
import json, os, subprocess, sys, tempfile, urllib.parse
from datetime import datetime, timezone

STATE = os.path.join(os.environ["FIX"], "gh.json")
st = json.load(open(STATE))
args = sys.argv[1:]
st["calls"].append(" ".join(args))
assert args[0] == "api", args
method, endpoint, fields, jq, silent, i = None, None, {}, None, False, 1
while i < len(args):
    a = args[i]
    if a == "--paginate": pass
    elif a == "--silent": silent = True
    elif a == "--jq": i += 1; jq = args[i]
    elif a == "-X": i += 1; method = args[i]
    elif a in ("-f", "-F"):
        i += 1; k, v = args[i].split("=", 1)
        fields[k] = (v == "true") if a == "-F" and v in ("true", "false") else v
    else: endpoint = a
    i += 1
method = method or ("POST" if fields else "GET")
path, _, query = endpoint.partition("?")
q = dict(urllib.parse.parse_qsl(query))
parts = path.split("/")[3:]
origin = st["origin"]


def die(msg):
    json.dump(st, open(STATE, "w"))
    print(msg, file=sys.stderr)
    sys.exit(1)


def sha(ref):
    out = subprocess.run(["git", "--git-dir", origin, "rev-parse", "--verify", "-q", f"refs/heads/{ref}"],
                         capture_output=True, text=True)
    return out.stdout.strip() or None


def pull(p):
    return {"number": p["number"], "state": p["state"], "draft": p["draft"], "title": p["title"],
            "body": p["body"], "merged_at": p["merged_at"], "mergeable": p.get("mergeable", True),
            "html_url": f"https://github.com/acme/app/pull/{p['number']}",
            "base": {"ref": p["base"]}, "head": {"ref": p["head"], "sha": p.get("merged_sha") or sha(p["head"])}}


def issue(n):
    i = st["issues"].get(str(n)) or die(f"HTTP 404 issue {n}")
    return dict(i, labels=[{"name": l} for l in i["labels"]])


out = None
if method == "GET" and parts == []:
    out = {"default_branch": "main"}
elif parts == ["issues"] and method == "GET":
    out = [issue(n) for n in st["issues"]]
elif len(parts) == 2 and parts[0] == "issues" and method == "GET":
    out = issue(parts[1])
elif len(parts) == 2 and parts[0] == "issues" and method == "PATCH":
    st["issues"][parts[1]].update(state=fields["state"])
elif parts[:1] == ["issues"] and parts[2:] == ["sub_issues"]:
    out = [{"number": n} for n in st.get("sub_issues", [])]
elif parts[:1] == ["issues"] and parts[2:] == ["comments"] and method == "GET":
    out = [c for c in st["comments"] if c["issue"] == int(parts[1])]
elif parts[:1] == ["issues"] and parts[2:] == ["comments"] and method == "POST":
    st["comments"].append({"id": 900 + len(st["comments"]), "issue": int(parts[1]), "body": fields["body"]})
elif parts[:2] == ["issues", "comments"] and method == "PATCH":
    next(c for c in st["comments"] if c["id"] == int(parts[2]))["body"] = fields["body"]
elif parts[:1] == ["labels"] and len(parts) == 2:
    name = urllib.parse.unquote(parts[1])
    if name not in st.setdefault("labels", []):
        die("HTTP 404 label")
    out = {"name": name}
elif parts == ["labels"] and method == "POST":
    st.setdefault("labels", []).append(fields["name"])
elif parts[:1] == ["issues"] and parts[2:] == ["labels"] and method == "POST":
    if fields["labels[]"] not in st.get("labels", []):
        die("HTTP 422 label missing")
    st["issues"][parts[1]]["labels"].append(fields["labels[]"])
elif parts[:1] == ["issues"] and parts[2:3] == ["labels"] and method == "DELETE":
    labels = st["issues"][parts[1]]["labels"]
    name = urllib.parse.unquote(parts[3])
    if name not in labels:
        die("HTTP 404 label")
    labels.remove(name)
elif parts == ["pulls"] and method == "GET":
    head = q.get("head", "").split(":")[-1]
    out = [pull(p) for p in st["pulls"] if (q.get("state") in (None, "all") or p["state"] == q["state"])
           and p["base"] == q.get("base", p["base"]) and (not head or p["head"] == head)]
elif parts == ["pulls"] and method == "POST":
    if not sha(fields["head"]):
        die("HTTP 422 head not on origin")
    p = {"number": 100 + len(st["pulls"]), "state": "open", "draft": fields.get("draft", False),
         "title": fields["title"], "body": fields["body"], "base": fields["base"], "head": fields["head"],
         "merged_at": None}
    st["pulls"].append(p)
    out = pull(p)
elif parts[:1] == ["pulls"] and len(parts) == 2 and method == "PATCH":
    next(p for p in st["pulls"] if p["number"] == int(parts[1]))["body"] = fields["body"]
elif parts[:1] == ["pulls"] and len(parts) == 2:
    out = pull(next(p for p in st["pulls"] if p["number"] == int(parts[1])))
elif parts[:1] == ["pulls"] and parts[2:] == ["merge"] and method == "PUT":
    p = next(p for p in st["pulls"] if p["number"] == int(parts[1]))
    if fields.get("sha") != sha(p["head"]):
        die("HTTP 409 head moved")
    work = tempfile.mkdtemp()
    for cmd in (["clone", "-q", origin, work], ["-C", work, "checkout", "-q", p["base"]],
                ["-C", work, "merge", "-q", "--no-ff", "-m", f"Merge pull request #{p['number']} from acme/{p['head']}",
                 f"origin/{p['head']}"], ["-C", work, "push", "-q", "origin", p["base"]]):
        subprocess.run(["git", *cmd], check=True, capture_output=True)
    p.update(state="closed", merged_at=datetime.now(timezone.utc).isoformat(), merged_sha=sha(p["head"]))
else:
    die(f"unexpected gh {' '.join(args)}")

json.dump(st, open(STATE, "w"))
if out is not None and not silent:
    if jq:
        sys.stdout.write(subprocess.run(["jq", "-rc", jq], input=json.dumps(out), capture_output=True,
                                        text=True, check=True).stdout)
    else:
        print(json.dumps(out))
"""

GATE = 'echo run >> "$COUNTER"; test ! -f RED'


class Cli(unittest.TestCase):
    """The script end to end: real git against a bare origin, a fake `gh` holding the tracker."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.origin = self.tmp / "origin.git"
        self.repo = self.tmp / "repo"
        self.counter = self.tmp / "gate-runs"
        (self.tmp / "bin").mkdir()
        gh = self.tmp / "bin" / "gh"
        gh.write_text(f"#!{sys.executable}\n{FAKE_GH}")
        gh.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{self.tmp / 'bin'}:{os.environ['PATH']}", FIX=str(self.tmp),
                        COUNTER=str(self.counter), DRIVE_SPEC_POLL_SECONDS="0",
                        DRIVE_SPEC_VERIFY_LOCK=str(self.tmp / "verify.lock"), CLAUDE_CODE_REMOTE="false",
                        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                        GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
        self.git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(self.tmp, "clone", "-q", str(self.origin), str(self.repo))
        self.commit(self.repo, "README", "hello\n", "Start")
        self.git(self.repo, "push", "-q", "origin", "main", "main:agent/local-spec-10-export")
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "drive-spec.json").write_text(json.dumps({"verify": GATE}))
        with open(self.repo / ".git" / "info" / "exclude", "a") as f:
            f.write(".claude/\n")
        self.spec_wt = self.repo / ".claude" / "worktrees" / "spec-10"
        self.git(self.repo, "worktree", "add", "-q", str(self.spec_wt), "-b", "agent/local-spec-10-export",
                 "origin/agent/local-spec-10-export")
        self.wt = self.slice(11, "serializer")
        self.commit(self.wt, "a.txt", "a\n", "Add the serializer")
        self.state = {
            "origin": str(self.origin), "calls": [], "pulls": [], "comments": [],
            "issues": {
                "10": self.issue(10, "Export reports", "## Problem\n\nNo export.\n"),
                "11": self.issue(11, "Create the serializer", "## Parent\n\n#10\n", ["agent:in-progress"]),
                "12": self.issue(12, "Wire the route", "## Parent\n\n#10\n\n## Blocked by\n\n#11\n"),
            },
        }
        self.save()

    def issue(self, n, title, body, labels=()):
        return {"number": n, "title": title, "body": body, "state": "open", "labels": list(labels)}

    def slice(self, m, slug):
        wt = self.repo / ".claude" / "worktrees" / f"issue-{m}"
        self.git(self.repo, "worktree", "add", "-q", str(wt), "-b", f"agent/issue-{m}-{slug}", "agent/local-spec-10-export")
        return wt

    def git(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True, capture_output=True,
                              text=True).stdout.strip()

    def commit(self, cwd, name, text, message):
        (Path(cwd) / name).write_text(text)
        self.git(cwd, "add", name)
        self.git(cwd, "commit", "-q", "-m", message)
        return self.git(cwd, "rev-parse", "HEAD")

    def save(self):
        (self.tmp / "gh.json").write_text(json.dumps(self.state))

    def gh_state(self):
        return json.loads((self.tmp / "gh.json").read_text())

    def run_ds(self, *args, cwd=None):
        return subprocess.run([str(SCRIPT), *args], cwd=cwd or self.repo, capture_output=True, text=True,
                              env=self.env)

    def gate_runs(self):
        return len(self.counter.read_text().splitlines()) if self.counter.exists() else 0

    def origin_sha(self, ref):
        return self.git(self.tmp, "--git-dir", str(self.origin), "rev-parse", ref)

    def comments(self, n):
        return [c["body"] for c in self.gh_state()["comments"] if c["issue"] == n]

    def status_file(self):
        return json.loads((self.repo / ".git" / "drive-spec" / "status" / "spec-10.json").read_text())

    def edit_state(self, fn):
        self.state = self.gh_state()
        fn(self.state)
        self.save()

    def land_11(self):
        out = self.run_ds("integrate", "10", "11", "--deviations", "none")
        self.assertEqual(out.returncode, 0, out.stderr)
        out = self.run_ds("land", "10", "11")
        self.assertEqual(out.returncode, 0, out.stderr)

    def advance_spec(self, name, text):
        """Another slice lands on the spec branch."""
        work = self.tmp / f"other-{name}"
        self.git(self.tmp, "clone", "-q", "-b", "agent/local-spec-10-export", str(self.origin), str(work))
        self.commit(work, name, text, f"Add {name}")
        self.git(work, "push", "-q", "origin", "agent/local-spec-10-export")


class Plan(Cli):
    def test_json(self):
        self.state["sub_issues"] = [11, 15]
        self.state["issues"]["11"]["labels"].append("needs:desktop")
        self.save()
        (self.repo / ".claude" / "drive-spec.json").write_text(json.dumps({"localOnly": {"label": "needs:desktop"}}))
        self.env["CLAUDE_CODE_REMOTE"] = "true"
        out = self.run_ds("plan", "#10", "--json")
        self.assertEqual(out.returncode, 0, out.stderr)
        p = json.loads(out.stdout)
        self.assertEqual(p["spec_branch"], "agent/local-spec-10-export")
        self.assertEqual(p["invisible"], [15])
        self.assertEqual([(s["number"], s["state"]) for s in p["slices"]], [(11, "held"), (12, "todo")])

    def test_text_from_inside_a_worktree(self):
        self.git(self.wt, "push", "-q", "origin", "agent/issue-11-serializer")
        out = self.run_ds("plan", "10", cwd=self.wt)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("#11  in-flight    Create the serializer", out.stdout)
        self.assertIn("#12  todo         Wire the route  after #11", out.stdout)

    def test_refusal_exits_2(self):
        self.state["issues"]["10"]["body"] = "## Parent\n\n#1\n"
        self.save()
        out = self.run_ds("plan", "10")
        self.assertEqual(out.returncode, 2)
        self.assertIn("refuse: #10 has a ## Parent of its own", out.stdout)

    def test_tracker_failure_is_loud(self):
        (self.tmp / "bin" / "gh").write_text("#!/bin/sh\necho 'HTTP 401' >&2; exit 1\n")
        out = self.run_ds("plan", "10")
        self.assertEqual(out.returncode, 1)
        self.assertIn("HTTP 401", out.stderr)


class Verify(Cli):
    def test_green_is_recorded_once_per_commit(self):
        out = self.run_ds("verify", "10", str(self.wt))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertRegex(out.stdout, r"^green [0-9a-f]{12}\n$")
        again = self.run_ds("verify", "10", str(self.wt))
        self.assertIn("(already verified)", again.stdout)
        self.assertEqual(self.gate_runs(), 1)

    def test_red_exits_4_and_is_not_trusted(self):
        self.commit(self.wt, "RED", "", "Break the gate")
        out = self.run_ds("verify", "10", str(self.wt))
        self.assertEqual(out.returncode, 4)
        self.assertIn("red ", out.stdout)
        self.assertEqual(self.run_ds("verify", "10", str(self.wt)).returncode, 4)
        self.assertEqual(self.gate_runs(), 2)

    def test_uncommitted_changes_refused(self):
        (self.wt / "b.txt").write_text("b")
        out = self.run_ds("verify", "10", str(self.wt))
        self.assertEqual(out.returncode, 2)
        self.assertIn("uncommitted changes", out.stderr)
        self.assertEqual(self.gate_runs(), 0)

    def test_pinned_gate_wins_over_config(self):
        self.assertEqual(self.run_ds("gate", "10").stdout.strip(), GATE)
        self.run_ds("gate", "10", "false")
        self.assertEqual(self.run_ds("gate", "10").stdout.strip(), "false")
        self.assertEqual(self.run_ds("verify", "10", str(self.wt)).returncode, 4)

    def test_no_gate_refused(self):
        (self.repo / ".claude" / "drive-spec.json").write_text("{}")
        out = self.run_ds("verify", "10", str(self.wt))
        self.assertEqual(out.returncode, 2)
        self.assertIn("no verify gate", out.stderr)

    def hanging_gate(self, minutes):
        (self.repo / ".claude" / "drive-spec.json").write_text(json.dumps(
            {"verify": 'sleep 60 & echo $! > "$FIX/sleep.pid"; wait', "verifyTimeoutMinutes": minutes}))

    def sleep_pid(self):
        f = self.tmp / "sleep.pid"
        for _ in range(100):
            if f.exists() and f.read_text().strip():
                return int(f.read_text())
            time.sleep(0.05)
        self.fail("the gate never started")

    def assertGone(self, pid):
        for _ in range(100):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout
            if state.strip().startswith("Z"):
                return
            time.sleep(0.05)
        self.fail(f"pid {pid} still runs")

    def test_overrunning_gate_is_stopped_whole_and_red(self):
        self.hanging_gate(0.02)
        out = self.run_ds("verify", "10", str(self.wt))
        self.assertEqual(out.returncode, 4)
        self.assertIn("timed out after 0.02 minutes", out.stdout)
        self.assertGone(self.sleep_pid())
        with open(self.tmp / "verify.lock", "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_killed_verify_takes_its_gate_with_it(self):
        self.hanging_gate(5)
        proc = subprocess.Popen([str(SCRIPT), "verify", "10", str(self.wt)], cwd=self.repo, env=self.env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pid = self.sleep_pid()
        proc.terminate()
        self.assertEqual(proc.wait(timeout=15), 128 + 15)
        self.assertGone(pid)
        self.assertFalse((self.repo / ".git" / "drive-spec" / "spec-10" / "verified").exists())

    def test_waiting_for_the_lock_names_its_holder(self):
        lock = open(self.tmp / "verify.lock", "a+")
        fcntl.flock(lock, fcntl.LOCK_EX)
        lock.write("pid 1 verifying abc in /elsewhere\n")
        lock.flush()
        proc = subprocess.Popen([str(SCRIPT), "verify", "10", str(self.wt)], cwd=self.repo, env=self.env,
                                stdout=subprocess.PIPE, text=True)
        self.assertEqual(proc.stdout.readline(), "waiting for the verify lock, held by pid 1 verifying abc in /elsewhere\n")
        lock.close()
        with proc.stdout:
            self.assertRegex(proc.stdout.read(), r"^green ")
        self.assertEqual(proc.wait(timeout=15), 0)

    def test_pr_head_verified_outside_a_spec_run(self):
        out = self.run_ds("verify", "pr-33", str(self.wt), "--gate", "true")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(any((self.repo / ".git" / "drive-spec" / "pr-33" / "verified").iterdir()))
        self.assertIn("(already verified)", self.run_ds("verify", "pr-33", str(self.wt), "--gate", "true").stdout)
        self.assertNotIn("(already verified)", self.run_ds("verify", "pr-33", str(self.wt), "--gate", "false").stdout)

    def test_only_the_pinned_gate_decides(self):
        (self.wt / "RED").write_text("x")
        self.git(self.wt, "add", "RED")
        self.git(self.wt, "commit", "-qm", "Break the gate")
        out = self.run_ds("verify", "10", str(self.wt), "--gate", "true")
        self.assertEqual(out.returncode, 2)
        self.assertIn("--gate goes with pr-<n> only", out.stderr)
        self.run_ds("gate", "10", "true")
        self.assertEqual(self.run_ds("verify", "10", str(self.wt)).returncode, 0)
        self.run_ds("gate", "10", GATE)
        out = self.run_ds("verify", "10", str(self.wt))
        self.assertEqual(out.returncode, 4, out.stdout)
        self.assertEqual(self.run_ds("integrate", "10", "11", "--deviations", "none").returncode, 4)
        self.assertFalse(any(p["merged_at"] for p in self.gh_state()["pulls"]))


class Integrate(Cli):
    def test_opens_pr_and_merges_at_the_verified_head(self):
        out = self.run_ds("integrate", "10", "11", "--deviations", "Deviations:\n- none of note")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        pr = self.gh_state()["pulls"][0]
        self.assertEqual((pr["base"], pr["head"], pr["state"]),
                         ("agent/local-spec-10-export", "agent/issue-11-serializer", "closed"))
        self.assertEqual(pr["title"], "Create the serializer")
        self.assertEqual(pr["body"], "Slice of #10. Ref #11.\n\nDeviations:\n- none of note")
        self.git(self.wt, "fetch", "-q", "origin")
        self.assertEqual(self.git(self.wt, "show", "origin/agent/local-spec-10-export:a.txt"), "a")

    def test_skips_the_gate_on_an_already_verified_head(self):
        self.run_ds("verify", "10", str(self.wt))
        out = self.run_ds("integrate", "10", "11", "--deviations", "none")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.gate_runs(), 1)

    def test_reverifies_after_merging_an_advanced_spec_branch(self):
        self.run_ds("verify", "10", str(self.wt))
        self.advance_spec("other.txt", "o\n")
        out = self.run_ds("integrate", "10", "11", "--deviations", "none")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.gate_runs(), 2)
        self.assertTrue((self.wt / "other.txt").exists())

    def test_red_after_merge_does_not_merge(self):
        self.run_ds("verify", "10", str(self.wt))
        self.advance_spec("RED", "")
        out = self.run_ds("integrate", "10", "11", "--deviations", "none")
        self.assertEqual(out.returncode, 4)
        self.assertIn("halt the run", out.stdout)
        self.assertEqual(self.gh_state()["pulls"][0]["state"], "open")

    def test_conflict_exits_3_with_a_clean_worktree(self):
        self.advance_spec("a.txt", "theirs\n")
        out = self.run_ds("integrate", "10", "11", "--deviations", "none")
        self.assertEqual(out.returncode, 3, out.stderr)
        self.assertIn("conflict merging agent/local-spec-10-export", out.stdout)
        self.assertIn("a.txt", out.stdout)
        self.assertEqual(self.git(self.wt, "status", "--porcelain"), "")
        self.assertEqual(self.gh_state()["pulls"][0]["state"], "open")

    def test_conflict_resolved_by_a_merger_then_integrates(self):
        self.advance_spec("a.txt", "theirs\n")
        self.run_ds("integrate", "10", "11", "--deviations", "none")
        self.git(self.wt, "fetch", "-q", "origin")
        subprocess.run(["git", "merge", "origin/agent/local-spec-10-export"], cwd=self.wt, env=self.env,
                       capture_output=True)
        (self.wt / "a.txt").write_text("both\n")
        self.git(self.wt, "commit", "-qam", "Merge the spec branch")
        out = self.run_ds("integrate", "10", "11")
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_commit_with_a_body_refused(self):
        (self.wt / "b.txt").write_text("b")
        self.git(self.wt, "add", "b.txt")
        self.git(self.wt, "commit", "-q", "-m", "Add b", "-m", "Co-Authored-By: someone")
        out = self.run_ds("integrate", "10", "11", "--deviations", "none")
        self.assertEqual(out.returncode, 2)
        self.assertIn("Add b", out.stderr)
        self.assertEqual(self.gh_state()["pulls"], [])

    def test_new_pr_needs_deviations(self):
        out = self.run_ds("integrate", "10", "11")
        self.assertEqual(out.returncode, 2)
        self.assertIn("--deviations", out.stderr)

    def test_deviations_from_stdin(self):
        out = subprocess.run([str(SCRIPT), "integrate", "10", "11", "--deviations", "-"], cwd=self.repo,
                             input="- built as a modal\n", capture_output=True, text=True, env=self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(self.gh_state()["pulls"][0]["body"].endswith("Deviations:\n- built as a modal"))

    def test_one_integration_at_a_time(self):
        notes = self.repo / ".git" / "drive-spec" / "spec-10"
        notes.mkdir(parents=True)
        with open(notes / "integrate.lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            out = self.run_ds("integrate", "10", "11", "--deviations", "none")
        self.assertEqual(out.returncode, 2)
        self.assertIn("one slice at a time", out.stderr)

    def test_dirty_worktree_refused(self):
        (self.wt / "a.txt").write_text("changed")
        self.assertEqual(self.run_ds("integrate", "10", "11", "--deviations", "none").returncode, 2)


class Land(Cli):
    def integrate(self):
        out = self.run_ds("integrate", "10", "11", "--deviations", "none")
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_lands_a_merged_slice(self):
        self.integrate()
        out = self.run_ds("land", "10", "11")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("landed #11 via #100; landed 1/2", out.stdout)
        st = self.gh_state()
        self.assertEqual(st["issues"]["11"]["state"], "closed")
        self.assertEqual(st["issues"]["11"]["labels"], [])
        comments = {c["issue"]: c["body"] for c in st["comments"]}
        self.assertEqual(comments[11], "Landed in #100 on `agent/local-spec-10-export`.")
        self.assertIn("- [x] #11 Create the serializer\n- [ ] #12 Wire the route\n\nSpec PR: #101", comments[10])
        spec_pr = st["pulls"][1]
        self.assertEqual((spec_pr["base"], spec_pr["head"], spec_pr["draft"]), ("main", "agent/local-spec-10-export", True))
        self.assertTrue(spec_pr["body"].startswith("Ref #10\n"))
        self.assertFalse(self.wt.exists())
        self.assertEqual(self.git(self.repo, "branch", "--list", "agent/issue-11-*"), "")
        self.assertEqual(self.git(self.repo, "ls-remote", "--heads", "origin", "agent/issue-11-*"), "")
        self.assertEqual(self.git(self.spec_wt, "rev-parse", "HEAD"), self.origin_sha("agent/local-spec-10-export"))
        status = json.loads((self.repo / ".git" / "drive-spec" / "status" / "spec-10.json").read_text())
        self.assertEqual((status["step"], status["state"], status["summary"]), ("build", "running", "landed 1/2"))
        self.assertEqual(status["pr_url"], "https://github.com/acme/app/pull/101")

    def test_rerun_is_idempotent(self):
        self.integrate()
        self.run_ds("land", "10", "11")
        out = self.run_ds("land", "10", "11")
        self.assertEqual(out.returncode, 0, out.stderr)
        st = self.gh_state()
        self.assertEqual(len(st["pulls"]), 2)
        self.assertEqual(sorted(c["issue"] for c in st["comments"]), [10, 11])

    def test_second_landing_reuses_the_spec_pr_and_marks_building(self):
        self.integrate()
        self.run_ds("land", "10", "11")
        self.state = self.gh_state()
        self.state["issues"]["12"]["labels"] = ["agent:in-progress"]
        self.save()
        out = self.run_ds("progress", "10")
        self.assertEqual(out.returncode, 0, out.stderr)
        st = self.gh_state()
        self.assertEqual(len(st["pulls"]), 2)
        progress = [c["body"] for c in st["comments"] if c["issue"] == 10]
        self.assertEqual(len(progress), 1)
        self.assertIn("- [ ] #12 Wire the route ← building", progress[0])

    def test_unmerged_slice_refused(self):
        out = self.run_ds("land", "10", "11")
        self.assertEqual(out.returncode, 2)
        self.assertIn("integrate it first", out.stderr)
        self.assertTrue(self.wt.exists())

    def test_not_a_slice_refused(self):
        self.assertEqual(self.run_ds("land", "10", "99").returncode, 2)


def slices(*specs):
    """Plan slices from (number, state, blockers, labels) tuples, already in build order."""
    return {"slices": [{"number": n, "title": f"Slice {n}", "state": st, "blockers": list(b), "labels": list(l),
                        "branch": f"agent/issue-{n}-x" if st in ("in-flight", "open-pr") else None,
                        "pr": 40 + n if st == "open-pr" else None} for n, st, b, l in specs]}


def picked(f):
    return [(p["number"], p["action"]) for p in f["picks"]]


class Pick(unittest.TestCase):
    def test_parallel_takes_the_whole_frontier_with_actions(self):
        f = ds.pick(slices((11, "closed", [], []), (12, "todo", [11], []), (13, "in-flight", [11], []),
                           (14, "open-pr", [], []), (15, "todo", [12], [])))
        self.assertEqual(picked(f), [(12, "build"), (13, "continue"), (14, "integrate")])
        self.assertIsNone(f["stop"])

    def test_sequential_takes_the_lowest_and_waits_while_one_runs(self):
        plan = slices((12, "todo", [], []), (11, "todo", [], []))
        self.assertEqual(picked(ds.pick(plan, parallel=False)), [(11, "build")])
        f = ds.pick(plan, running=[11], parallel=False)
        self.assertEqual((picked(f), f["running"], f["stop"]), ([], [11], None))
        self.assertIn("wait:", ds.render_picks(f))

    def test_running_slices_are_not_picked_again(self):
        f = ds.pick(slices((11, "todo", [], []), (12, "todo", [], [])), running=[11, 99])
        self.assertEqual((picked(f), f["running"]), ([(12, "build")], [11]))

    def test_local_only_slices_never_build_beside_each_other(self):
        plan = slices((11, "todo", [], ["needs:desktop"]), (12, "todo", [], ["needs:desktop"]), (13, "todo", [], []))
        self.assertEqual(picked(ds.pick(plan, local_label="needs:desktop")), [(11, "build"), (13, "build")])
        f = ds.pick(plan, running=[11], local_label="needs:desktop")
        self.assertEqual(picked(f), [(13, "build")])

    def test_ceiling_limits_picks_then_stops(self):
        plan = slices((11, "todo", [], []), (12, "todo", [], []), (13, "todo", [], []))
        self.assertEqual(picked(ds.pick(plan, max_slices=3, landed=1)), [(11, "build"), (12, "build")])
        self.assertEqual(picked(ds.pick(plan, running=[11], max_slices=2, landed=1)), [])
        f = ds.pick(plan, max_slices=2, landed=2)
        self.assertEqual(f["stop"], "ceiling")
        self.assertIn("stop: ceiling, 2 landed this run", ds.render_picks(f))

    def test_only_held_and_what_they_block_stops(self):
        f = ds.pick(slices((11, "closed", [], []), (12, "held", [11], []), (13, "todo", [12], [])))
        self.assertEqual((f["stop"], f["held"]), ("held", [12]))
        self.assertIn("stop: held, only held slices and those they block remain: #12", ds.render_picks(f))

    def test_done_and_blocked(self):
        self.assertEqual(ds.pick(slices((11, "closed", [], [])))["stop"], "done")
        f = ds.pick(slices((11, "todo", [], ["agent:blocked"])))
        self.assertEqual((f["stop"], f["blocked"]), ("blocked", [11]))


class Brief(unittest.TestCase):
    def run_(self, config):
        return types.SimpleNamespace(config=config, repo="acme/app", spec=10, notes=Path("/n"))

    def test_fills_every_placeholder(self):
        b = ds.brief(self.run_({"localOnly": {"label": "needs:desktop", "proof": "docs/proof.md"}}),
                     12, Path("/w/issue-12"), "main", True, True)
        self.assertNotRegex(b, r"<[a-z][a-z ]*>|<If ")
        for part in ["Worktree: /w/issue-12.", "gh api repos/acme/app/issues/12", "Spec: #10",
                     "git log --oneline origin/main..HEAD", "/n/issue-12.md", "drive-spec verify 10 /w/issue-12",
                     "carry on.", "carries `needs:desktop`", "`docs/proof.md`"]:
            self.assertIn(part, b)

    def test_drops_conditions_that_do_not_hold(self):
        b = ds.brief(self.run_({}), 12, Path("/w/issue-12"), "main", False, False)
        self.assertNotIn("carry on", b)
        self.assertNotIn("prove it", b)
        self.assertNotRegex(b, r"<[a-z][a-z ]*>|<If ")


class Frontier(Cli):
    def test_text(self):
        out = self.run_ds("frontier", "10")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout, "build #11 Create the serializer\n")

    def test_inbox_comes_first(self):
        status = self.repo / ".git" / "drive-spec" / "status"
        status.mkdir(parents=True)
        (status / "spec-10.inbox.md").write_text("## main advanced: #5\nOverlaps your branch: none\n")
        out = self.run_ds("frontier", "10")
        self.assertEqual(out.returncode, 5)
        self.assertIn("## main advanced: #5", out.stdout)
        self.assertEqual(self.run_ds("frontier", "10").returncode, 0)

    def test_integrate_checks_the_inbox_too(self):
        status = self.repo / ".git" / "drive-spec" / "status"
        status.mkdir(parents=True)
        (status / "spec-10.inbox.md").write_text("## main advanced: #5\n")
        self.assertEqual(self.run_ds("integrate", "10", "11", "--deviations", "none").returncode, 5)
        self.assertEqual(self.gh_state()["pulls"], [])

    def test_blocked_slice_refuses(self):
        self.edit_state(lambda st: st["issues"]["11"]["labels"].append("agent:blocked"))
        out = self.run_ds("frontier", "10")
        self.assertEqual(out.returncode, 2)
        self.assertIn("#11 carries agent:blocked", out.stderr)

    def test_ceiling_counts_landings_since_the_gate_was_pinned(self):
        out = self.run_ds("frontier", "10", "--max", "1")
        self.assertEqual(out.returncode, 2)
        self.assertIn("pin the gate", out.stderr)
        self.run_ds("gate", "10", GATE)
        self.land_11()
        self.assertEqual(self.run_ds("frontier", "10", "--max", "1").stdout, "stop: ceiling, 1 landed this run\n")
        self.run_ds("gate", "10", GATE)
        self.assertEqual(self.run_ds("frontier", "10", "--max", "1").stdout, "build #12 Wire the route\n")


class Start(Cli):
    def test_fresh_slice_from_the_spec_head(self):
        (self.repo / ".claude" / "drive-spec.json").write_text(
            json.dumps({"verify": GATE, "bootstrap": 'echo boot >> "$COUNTER.boot"'}))
        self.land_11()
        out = self.run_ds("start", "10", "12")
        self.assertEqual(out.returncode, 0, out.stderr)
        wt = self.repo / ".claude" / "worktrees" / "issue-12"
        self.assertTrue(out.stdout.startswith(f"worktree {wt} on agent/issue-12-wire-the-route\n"))
        self.assertEqual(self.git(wt, "rev-parse", "HEAD"), self.origin_sha("agent/local-spec-10-export"))
        self.assertTrue((wt / "a.txt").exists())
        self.assertTrue(Path(f"{self.counter}.boot").exists())
        self.assertIn(f"drive-spec verify 10 {wt}", out.stdout)
        self.assertNotIn("carry on", out.stdout)
        self.assertIn("agent:in-progress", self.gh_state()["issues"]["12"]["labels"])
        self.assertEqual(self.status_file()["next"], "implementer builds #12")

    def test_not_on_the_frontier_refused(self):
        out = self.run_ds("start", "10", "12")
        self.assertEqual(out.returncode, 2)
        self.assertIn("blocked by #11", out.stderr)

    def test_existing_worktree_continues(self):
        out = self.run_ds("start", "10", "11")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("carry on", out.stdout)
        self.assertEqual(self.gh_state()["issues"]["11"]["labels"], ["agent:in-progress"])

    def test_local_branch_without_worktree_keeps_its_commits(self):
        head = self.git(self.wt, "rev-parse", "HEAD")
        self.git(self.repo, "worktree", "remove", str(self.wt))
        out = self.run_ds("start", "10", "11")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.git(self.wt, "rev-parse", "HEAD"), head)

    def test_branch_on_origin_is_restored(self):
        self.git(self.wt, "push", "-q", "origin", "agent/issue-11-serializer")
        head = self.git(self.wt, "rev-parse", "HEAD")
        self.git(self.repo, "worktree", "remove", str(self.wt))
        self.git(self.repo, "branch", "-D", "agent/issue-11-serializer")
        out = self.run_ds("start", "10", "11")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.git(self.wt, "rev-parse", "HEAD"), head)


class Finish(Cli):
    def test_halt(self):
        out = self.run_ds("halt", "10", "11", "the", "export", "test", "fails.")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.gh_state()["issues"]["11"]["labels"], ["agent:blocked"])
        self.assertEqual(self.comments(11), [f"drive-spec halted here: the export test fails. Worktree kept at "
                                             f"{self.wt}. Resume with `/drive-spec 10` after fixing."])
        self.assertEqual(self.comments(10)[0], "drive-spec halted on #11: the export test fails.\n`/drive-spec 10`")
        st = self.status_file()
        self.assertEqual((st["state"], st["step"], st["next"]), ("halted", "build", "/drive-spec 10"))

    def test_done_needs_every_slice_closed(self):
        out = self.run_ds("finish", "10", "done")
        self.assertEqual(out.returncode, 2)
        self.assertIn("#11, #12 still open", out.stderr)
        self.assertEqual(self.comments(10), [])

    def test_done(self):
        self.land_11()
        self.edit_state(lambda st: st["issues"]["12"].update(state="closed"))
        out = self.run_ds("finish", "10", "done")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("drive-spec done: all 2 slices landed, review clean. Spec PR #101.", self.comments(10))
        st = self.status_file()
        self.assertEqual((st["state"], st["step"], st["next"]), ("done", "review-pr", "none"))

    def test_conflicts_post_the_list(self):
        self.assertEqual(self.run_ds("finish", "10", "conflicts").returncode, 2)
        notes = self.repo / ".git" / "drive-spec" / "spec-10"
        notes.mkdir(parents=True)
        (notes / "conflicts.md").write_text("- #11 says CSV; #12 says JSON\n")
        self.assertEqual(self.run_ds("finish", "10", "conflicts").returncode, 0)
        self.assertEqual(self.comments(10)[0], "drive-spec halted before building: the spec and its slices "
                                               "disagree.\n`/drive-spec 10`\n\n- #11 says CSV; #12 says JSON")
        self.assertEqual(self.status_file()["step"], "explore")

    def test_held_and_review_halt(self):
        self.assertEqual(self.run_ds("finish", "10", "held").returncode, 2)
        out = self.run_ds("finish", "10", "halted", "--why", "fix pass red", "--step", "review-pr",
                          "--resume", "/review-fix-pr 101")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.comments(10)[0], "drive-spec halted: fix pass red.\n`/review-fix-pr 101`")

    def test_refused(self):
        self.assertEqual(self.run_ds("finish", "10", "refused").returncode, 2)
        self.edit_state(lambda st: st["issues"]["10"].update(body="## Parent\n\n#1\n"))
        self.assertEqual(self.run_ds("finish", "10", "refused").returncode, 0)
        self.assertTrue(self.comments(10)[0].startswith("drive-spec refused #10: #10 has a ## Parent of its own"))
        self.assertEqual(self.status_file()["step"], "guard")


DISPATCH = SCRIPT.parent.parent / "dispatch" / "dispatch"
STATUS_DOC = SCRIPT.with_name("STATUS.md").read_text()


class DispatcherCase(Cli):
    """What the script writes is what the dispatcher reads: the contract in STATUS.md, read by `dispatch`."""

    def setUp(self):
        super().setUp()
        for name, out in (("herdr", "{}"), ("claude", "[]")):
            f = self.tmp / "bin" / name
            f.write_text(f"#!/bin/sh\necho '{out}'\n")
            f.chmod(0o755)

    def row(self):
        st = self.status_file()
        steps = re.search(r"`step` is the step's name: (.*)\.", STATUS_DOC).group(1)
        self.assertIn(f"`{st['step']}`", steps)
        self.assertIn(f"| `{st['state']}` |", STATUS_DOC.split("| `state` |", 1)[1].split("\n\n", 1)[0])
        for key in ("step", "state", "summary", "next"):
            self.assertTrue(st.get(key), key)
        self.assertNotIn("\n", st["summary"])
        out = subprocess.run([str(DISPATCH), "--repo", str(self.repo), "status", "--json"], capture_output=True,
                             text=True, env=self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        return next(r for r in json.loads(out.stdout) if str(r["spec"]) == "10")


class Dispatcher(DispatcherCase):
    def test_landing_is_running_with_branch_and_pr(self):
        self.land_11()
        st = self.status_file()
        self.assertEqual((st["branch"], st["pr_url"]),
                         ("agent/local-spec-10-export", "https://github.com/acme/app/pull/101"))
        self.assertEqual((self.row()["state"], self.row()["summary"]), ("running", "landed 1/2"))

    def test_start_is_running(self):
        self.run_ds("start", "10", "11")
        self.assertEqual(self.row()["state"], "running")
        self.assertEqual(self.status_file()["branch"], "agent/local-spec-10-export")

    def test_halt_relays_why_and_resume(self):
        self.run_ds("halt", "10", "11", "export test red")
        r = self.row()
        self.assertEqual((r["attention"], r["detail"]),
                         ("HALT", "drive-spec halted on #11: export test red. → /drive-spec 10"))

    def test_review_halt_resumes_with_review_fix_pr(self):
        self.land_11()
        self.run_ds("finish", "10", "halted", "--why", "fix pass red", "--step", "review-pr",
                    "--resume", "/review-fix-pr 101")
        r = self.row()
        self.assertEqual((r["attention"], r["step"]), ("HALT", "review-pr"))
        self.assertTrue(r["detail"].endswith("→ /review-fix-pr 101"))

    def test_pauses(self):
        self.run_ds("gate", "10", GATE)
        self.land_11()
        self.run_ds("finish", "10", "ceiling")
        r = self.row()
        self.assertEqual((r["attention"], r["detail"]),
                         ("PAUSE", "drive-spec paused at maxSlices: 1 of 2 slices landed. → /drive-spec 10"))

    def test_done_relays_the_pr_and_clears_a_question(self):
        self.land_11()
        subprocess.run([str(SCRIPT.with_name("status.sh")), "10", "question=keep CSV?", "question_blocking=false"],
                       cwd=self.repo, env=self.env)
        self.edit_state(lambda st: st["issues"]["12"].update(state="closed"))
        self.run_ds("finish", "10", "done")
        r = self.row()
        self.assertEqual((r["attention"], r["detail"], r["step"]),
                         ("PR", "https://github.com/acme/app/pull/101", "review-pr"))
        self.assertIsNone(self.status_file()["question"])

    def test_done_with_review_leftovers(self):
        self.land_11()
        self.edit_state(lambda st: st["issues"]["12"].update(state="closed"))
        out = subprocess.run([str(SCRIPT), "finish", "10", "done", "--left", "-"], cwd=self.repo, env=self.env,
                             input="- rename ExportJob\n", capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.comments(10)[-1], "drive-spec done: all 2 slices landed, review left findings open. "
                                                "Spec PR #101.\n\nLeft from review:\n- rename ExportJob")
        self.assertEqual(self.row()["attention"], "PR")
        self.assertEqual(self.run_ds("finish", "10", "held", "--left", "x").returncode, 2)

    def test_a_session_under_another_config_dir_is_seen(self):
        run_dir = self.tmp / "claude-on"
        (self.tmp / "bin" / "claude").write_text(
            f'#!/bin/sh\nif [ "$CLAUDE_CONFIG_DIR" = "{run_dir}" ]; then\n'
            f'echo \'[{{"sessionId": "run-1", "cwd": "{self.repo}", "name": "drive-spec-10", "status": "busy"}}]\'\n'
            "else echo '[]'; fi\n")
        subprocess.run([str(SCRIPT.with_name("status.sh")), "10", "step=build", "state=running", "summary=landed 0/2",
                        "next=x"], cwd=self.repo, env=dict(self.env, CLAUDE_CODE_SESSION_ID="run-1",
                                                           CLAUDE_CONFIG_DIR=str(run_dir)))
        self.assertEqual(self.status_file()["config_dir"], str(run_dir))
        self.env["CLAUDE_CONFIG_DIR"] = str(self.tmp / "claude-default")
        self.assertEqual(self.row()["session"], "busy")

    def test_launch_resumes_an_idle_pane_with_the_runs_next_command(self):
        prompts = self.tmp / "prompts"
        (self.tmp / "bin" / "herdr").write_text(
            '#!/bin/sh\nif [ "$1 $2" = "agent list" ]; then\n'
            f'echo \'{{"result": {{"agents": [{{"pane_id": "p1", "agent_status": "{{STATUS}}"}}]}}}}\'\n'
            f'else echo "$@" >> {prompts}; echo "{{}}"; fi\n')
        herdr = self.tmp / "bin" / "herdr"
        template = herdr.read_text()
        env = dict(self.env, HERDR_PANE_ID="p1", XDG_STATE_HOME=str(self.tmp / "state"), DISPATCH_MAX_TESTS="99",
                   DISPATCH_MAX_CPU="101", DISPATCH_MAX_MEMORY="101")

        def launch(status):
            herdr.write_text(template.replace("{STATUS}", status))
            prompts.unlink(missing_ok=True)
            out = subprocess.run([str(DISPATCH), "--repo", str(self.repo), "launch", "10"], capture_output=True,
                                 text=True, env=env)
            self.assertEqual(out.returncode, 0, out.stderr)
            return out.stdout.strip(), prompts.read_text().strip() if prompts.exists() else None

        self.env["HERDR_PANE_ID"] = "p1"
        self.run_ds("finish", "10", "halted", "--why", "fix pass red", "--step", "review-pr",
                    "--resume", "/review-fix-pr 101")
        self.assertEqual(launch("working"), ("10 already running in p1", None))
        self.assertEqual(launch("done"), ("10 resumed in p1 with /review-fix-pr 101", "agent prompt p1 /review-fix-pr 101"))
        subprocess.run([str(SCRIPT.with_name("status.sh")), "10", "state=running", "step=build"], cwd=self.repo, env=env)
        self.assertEqual(launch("idle"), ("10 resumed in p1 with /drive-spec 10", "agent prompt p1 /drive-spec 10"))

    def test_refusal_halts_at_guard(self):
        self.edit_state(lambda st: st["issues"]["10"].update(body="## Parent\n\n#1\n"))
        self.run_ds("finish", "10", "refused")
        r = self.row()
        self.assertEqual((r["attention"], r["step"]), ("HALT", "guard"))


class Open(DispatcherCase):
    def remove_spec_worktree(self):
        self.git(self.repo, "worktree", "remove", str(self.spec_wt))

    def test_fresh_spec_branch_is_cut_from_base_and_pushed(self):
        self.edit_state(lambda st: st["issues"].update({
            "30": self.issue(30, "Import reports!", "## Problem\n"),
            "31": self.issue(31, "Parse the file", "## Parent\n\n#30\n")}))
        out = self.run_ds("open", "30", "--base", "main")
        self.assertEqual(out.returncode, 0, out.stderr)
        wt = self.repo / ".claude" / "worktrees" / "spec-30"
        self.assertEqual(out.stdout, f"worktree {wt} on agent/local-spec-30-import-reports (cut from origin/main)\n")
        self.assertEqual(self.origin_sha("agent/local-spec-30-import-reports"), self.origin_sha("main"))
        st = json.loads((self.repo / ".git" / "drive-spec" / "status" / "spec-30.json").read_text())
        self.assertEqual((st["step"], st["branch"], st["base"]), ("worktree", "agent/local-spec-30-import-reports", "main"))

    def test_resume_takes_origin(self):
        self.remove_spec_worktree()
        self.advance_spec("other.txt", "o\n")
        out = self.run_ds("open", "10")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("(resumed)", out.stdout)
        self.assertEqual(self.git(self.spec_wt, "rev-parse", "HEAD"), self.origin_sha("agent/local-spec-10-export"))
        self.assertEqual(self.row()["step"], "worktree")

    def test_resume_keeps_unpushed_local_commits(self):
        head = self.commit(self.spec_wt, "merged-base.txt", "m\n", "Merge main")
        self.remove_spec_worktree()
        out = self.run_ds("open", "10")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.origin_sha("agent/local-spec-10-export"), head)

    def test_existing_worktree_pulls(self):
        self.advance_spec("other.txt", "o\n")
        out = self.run_ds("open", "10")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("(reused)", out.stdout)
        self.assertTrue((self.spec_wt / "other.txt").exists())

    def test_bootstrap_only_for_a_new_worktree(self):
        (self.repo / ".claude" / "drive-spec.json").write_text(json.dumps({"bootstrap": 'echo b >> "$COUNTER.boot"'}))
        self.run_ds("open", "10")
        self.assertFalse(Path(f"{self.counter}.boot").exists())
        self.remove_spec_worktree()
        self.run_ds("open", "10")
        self.assertEqual(Path(f"{self.counter}.boot").read_text(), "b\n")

    def test_refusals(self):
        self.git(self.spec_wt, "checkout", "-q", "-b", "elsewhere")
        out = self.run_ds("open", "10")
        self.assertEqual(out.returncode, 2)
        self.assertIn("is on elsewhere", out.stderr)
        self.edit_state(lambda st: st["issues"]["10"].update(body="## Parent\n\n#1\n"))
        self.assertEqual(self.run_ds("open", "10").returncode, 2)


class Confirm(DispatcherCase):
    def close_12(self):
        self.edit_state(lambda st: st["issues"]["12"].update(state="closed"))

    def test_refuses_with_an_open_slice(self):
        self.land_11()
        out = self.run_ds("confirm", "10")
        self.assertEqual(out.returncode, 2)
        self.assertIn("#12", out.stderr)

    def test_closes_the_spec_and_lists_deviations(self):
        out = self.run_ds("integrate", "10", "11", "--deviations", "Deviations:\n- export runs inline, no job")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.run_ds("land", "10", "11")
        self.close_12()
        out = self.run_ds("confirm", "10", "--left", "- rename ExportJob")
        self.assertEqual(out.returncode, 0, out.stderr)
        spec_pr = self.gh_state()["pulls"][1]
        self.assertEqual(spec_pr["body"], "Closes #10\n\nSlices, in build order:\n- #11 Create the serializer\n"
                                          "- #12 Wire the route\n\nDeviations:\n\n#11 Create the serializer\n"
                                          "- export runs inline, no job\n\nLeft from review:\n- rename ExportJob")
        self.assertTrue(spec_pr["draft"])
        r = self.row()
        self.assertEqual((r["step"], r["pr_url"]), ("confirm", "https://github.com/acme/app/pull/101"))

    def test_no_deviations_and_opens_a_missing_spec_pr(self):
        self.edit_state(lambda st: [st["issues"][n].update(state="closed") for n in ("11", "12")])
        out = self.run_ds("confirm", "10")
        self.assertEqual(out.returncode, 0, out.stderr)
        spec_pr = self.gh_state()["pulls"][0]
        self.assertEqual((spec_pr["base"], spec_pr["draft"]), ("main", True))
        self.assertTrue(spec_pr["body"].startswith("Closes #10\n"))
        self.assertTrue(spec_pr["body"].endswith("Deviations: none"))


class Cleanup(DispatcherCase):
    def finish_slices(self):
        self.run_ds("gate", "10", GATE)
        self.land_11()
        self.edit_state(lambda st: st["issues"]["12"].update(state="closed"))

    def test_removes_worktrees_and_notes(self):
        self.finish_slices()
        stray = self.slice(12, "route")
        out = self.run_ds("cleanup", "10")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout, "removed spec-10, issue-12, notes\nhttps://github.com/acme/app/pull/101\n")
        self.assertFalse(self.spec_wt.exists() or stray.exists())
        self.assertFalse((self.repo / ".git" / "drive-spec" / "spec-10").exists())
        self.assertTrue((self.repo / ".git" / "drive-spec" / "status" / "spec-10.json").exists())
        self.assertEqual(self.origin_sha("agent/local-spec-10-export"),
                         self.git(self.repo, "rev-parse", "agent/local-spec-10-export"))
        r = self.row()
        self.assertEqual((r["step"], r["state"], r["pr_url"]), ("review-pr", "running", "https://github.com/acme/app/pull/101"))
        self.assertTrue(self.status_file()["summary"].endswith("; reviewing and fixing PR #101"))

    def test_stops_what_still_runs_in_a_worktree(self):
        self.finish_slices()
        left = subprocess.Popen(["sleep", "60"], cwd=self.spec_wt)
        out = self.run_ds("cleanup", "10")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(f"stopped pid {left.pid} in spec-10: sleep 60", out.stdout)
        self.assertEqual(left.wait(timeout=5), -15)

    def test_refuses_with_an_open_slice(self):
        out = self.run_ds("cleanup", "10")
        self.assertEqual(out.returncode, 2)
        self.assertTrue(self.wt.exists())

    def test_refuses_to_lose_spec_work(self):
        self.finish_slices()
        (self.spec_wt / "wip.txt").write_text("w")
        self.assertIn("uncommitted", self.run_ds("cleanup", "10").stderr)
        self.git(self.spec_wt, "add", "wip.txt")
        self.git(self.spec_wt, "commit", "-qm", "Fix a review finding")
        self.assertIn("push them first", self.run_ds("cleanup", "10").stderr)
        self.assertTrue(self.spec_wt.exists())


class Boundaries(DispatcherCase):
    """Steps 1, 2, 4, 5 and 7 end in a status write; the steps after the spec branch exists read the inbox first."""

    def note(self, text="## main advanced: #5\nOverlaps your branch: none\n"):
        status = self.repo / ".git" / "drive-spec" / "status"
        status.mkdir(parents=True, exist_ok=True)
        (status / "spec-10.inbox.md").write_text(text)

    def notes(self):
        return self.repo / ".git" / "drive-spec" / "spec-10"

    def close_all(self):
        self.land_11()
        self.edit_state(lambda st: st["issues"]["12"].update(state="closed"))
        self.git(self.spec_wt, "pull", "-q", "origin", "agent/local-spec-10-export")

    def test_gate_resolves_the_base_afresh(self):
        subprocess.run([str(SCRIPT.with_name("status.sh")), "10", "base=develop", "step=done", "state=done",
                        "question=old?"], cwd=self.repo, env=self.env)
        self.assertEqual(self.run_ds("gate", "10", GATE).returncode, 0)
        st = self.status_file()
        self.assertEqual((st["step"], st["state"], st["base"], st["question"]), ("resolve", "running", "main", None))
        self.run_ds("gate", "10", GATE, "--base", "release")
        self.assertEqual(self.status_file()["base"], "release")
        self.assertEqual(self.row()["step"], "resolve")

    def test_plan_writes_guard_once(self):
        self.run_ds("plan", "10")
        self.assertFalse((self.repo / ".git" / "drive-spec" / "status" / "spec-10.json").exists())
        self.run_ds("gate", "10", GATE)
        self.run_ds("plan", "10", "--json")
        self.assertEqual(self.status_file()["step"], "resolve")
        self.run_ds("plan", "10")
        self.assertEqual((self.row()["step"], self.status_file()["summary"]), ("guard", "plan: landed 0/2; building #11"))
        self.run_ds("start", "10", "11")
        self.run_ds("plan", "10")
        self.assertEqual(self.status_file()["step"], "build")

    def test_open_reads_the_inbox_once_the_branch_exists(self):
        self.note()
        out = self.run_ds("open", "10")
        self.assertEqual(out.returncode, 5)
        self.assertIn("## main advanced: #5", out.stdout)
        self.assertEqual(self.status_file()["step"], "worktree")
        self.assertEqual(self.run_ds("open", "10").returncode, 0)

    def test_preview(self):
        out = self.run_ds("preview", "10", "--sequential")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith(f"base: main\nspec branch: agent/local-spec-10-export\nworktree root: "
                                              f"{self.repo / '.claude' / 'worktrees'}\nmode: sequential\n"
                                              f"ceiling: none\n\nspec #10 Export reports\n"), out.stdout)
        self.assertTrue(self.comments(10)[0].startswith("<!-- implement-spec -->"))
        self.assertEqual((self.row()["step"], self.row()["state"]), ("preview", "running"))

    def test_dry_run_pauses_at_preview(self):
        self.run_ds("preview", "10", "--dry-run")
        r = self.row()
        self.assertEqual((r["attention"], r["step"]), ("PAUSE", "preview"))
        self.assertEqual(self.status_file()["next"], "/drive-spec 10")

    def test_preview_reads_the_inbox_first(self):
        self.note()
        self.assertEqual(self.run_ds("preview", "10").returncode, 5)
        self.assertEqual(self.comments(10), [])

    def test_explored_needs_every_note_written_this_run(self):
        self.run_ds("gate", "10", GATE)
        (self.notes() / "issue-11.md").write_text("serializer\n")
        out = self.run_ds("explored", "10")
        self.assertEqual(out.returncode, 2)
        self.assertIn("no issue-12.md, conflicts.md", out.stderr)
        (self.notes() / "issue-12.md").write_text("route\n")
        (self.notes() / "conflicts.md").write_text("")
        os.utime(self.notes() / "conflicts.md", (0, 0))
        self.assertIn("predates this run", self.run_ds("explored", "10").stderr)
        (self.notes() / "conflicts.md").write_text("")
        out = self.run_ds("explored", "10")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual((self.row()["step"], self.status_file()["next"]), ("explore", "build the frontier"))

    def test_explored_halts_on_conflicts(self):
        self.run_ds("gate", "10", GATE)
        for name in ("issue-11.md", "issue-12.md"):
            (self.notes() / name).write_text("n\n")
        (self.notes() / "conflicts.md").write_text("- #11 says CSV; #12 says JSON\n")
        self.assertEqual(self.run_ds("explored", "10").returncode, 3)
        self.assertTrue(self.comments(10)[0].startswith("drive-spec halted before building"))
        r = self.row()
        self.assertEqual((r["attention"], r["step"]), ("HALT", "explore"))

    def test_reviewed_needs_a_pushed_green_head(self):
        self.run_ds("gate", "10", GATE)
        self.assertIn("not every slice is closed", self.run_ds("reviewed", "10").stderr)
        self.close_all()
        self.commit(self.spec_wt, "fix.txt", "f\n", "Fix a review finding")
        self.assertIn("push the fixes", self.run_ds("reviewed", "10").stderr)
        self.git(self.spec_wt, "push", "-q", "origin", "agent/local-spec-10-export")
        self.assertIn("not verified green", self.run_ds("reviewed", "10").stderr)
        self.run_ds("verify", "10", str(self.spec_wt))
        out = self.run_ds("reviewed", "10")
        self.assertEqual(out.returncode, 0, out.stderr)
        r = self.row()
        self.assertEqual((r["step"], r["pr_url"]), ("review", "https://github.com/acme/app/pull/101"))
        self.assertTrue(self.status_file()["summary"].startswith("review clean at "))

    def test_review_leftovers_carry_to_confirm_and_done(self):
        self.run_ds("gate", "10", GATE)
        self.close_all()
        self.run_ds("verify", "10", str(self.spec_wt))
        self.run_ds("reviewed", "10", "--left", "- rename ExportJob")
        self.assertEqual(self.run_ds("confirm", "10").returncode, 0)
        self.assertTrue(self.gh_state()["pulls"][1]["body"].endswith("\n\nLeft from review:\n- rename ExportJob"))
        self.assertEqual(self.run_ds("cleanup", "10").returncode, 0)
        out = self.run_ds("finish", "10", "done")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.comments(10)[-1], "drive-spec done: all 2 slices landed, review left findings open. "
                                                "Spec PR #101.\n\nLeft from review:\n- rename ExportJob")

    def test_confirm_and_cleanup_read_the_inbox_first(self):
        self.close_all()
        self.note()
        self.assertEqual(self.run_ds("confirm", "10").returncode, 5)
        self.note()
        self.assertEqual(self.run_ds("cleanup", "10").returncode, 5)
        self.assertTrue(self.spec_wt.exists())



class Heartbeat(DispatcherCase):
    def stale_status(self, **fields):
        subprocess.run([str(SCRIPT.with_name("status.sh")), "10", "step=build", "state=running", "summary=landed 0/2",
                        "next=x", *(f"{k}={v}" for k, v in fields.items())], cwd=self.repo, env=self.env)
        path = self.repo / ".git" / "drive-spec" / "status" / "spec-10.json"
        data = json.loads(path.read_text())
        path.write_text(json.dumps(dict(data, updated_at="2000-01-01T00:00:00Z", session_id="the-run")))

    def test_a_long_gate_keeps_the_run_fresh(self):
        self.stale_status()
        (self.repo / ".claude" / "drive-spec.json").write_text(json.dumps({"verify": "sleep 1.5"}))
        env = dict(self.env, DRIVE_SPEC_HEARTBEAT_SECONDS="0.3", CLAUDE_CODE_SESSION_ID="someone-else")
        out = subprocess.run([str(SCRIPT), "verify", "10", str(self.wt)], cwd=self.repo, env=env, capture_output=True,
                             text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        st = self.status_file()
        self.assertNotEqual(st["updated_at"], "2000-01-01T00:00:00Z")
        self.assertEqual((st["session_id"], st["summary"]), ("the-run", "landed 0/2"))
        self.assertNotEqual(self.row()["attention"], "STALL")

    def test_a_pr_gate_refreshes_the_spec_that_owns_the_pr(self):
        self.stale_status(pr_url="https://github.com/acme/app/pull/101")
        env = dict(self.env, DRIVE_SPEC_HEARTBEAT_SECONDS="0.3")
        out = subprocess.run([str(SCRIPT), "verify", "pr-101", str(self.wt), "--gate", "sleep 1.5"], cwd=self.repo,
                             env=env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotEqual(self.status_file()["updated_at"], "2000-01-01T00:00:00Z")


class Questions(DispatcherCase):
    def test_ask_waits_and_answered_records_the_decision(self):
        self.run_ds("gate", "10", GATE)
        out = self.run_ds("ask", "10", "Public or sign-in?\n(a) public (b) sign-in. Recommend (a).")
        self.assertEqual(out.returncode, 0, out.stderr)
        r = self.row()
        self.assertEqual((r["attention"], r["step"]), ("ASK", "resolve"))
        self.assertEqual(self.status_file()["question"], "Public or sign-in? (a) public (b) sign-in. Recommend (a).")
        out = self.run_ds("answered", "10", "public")
        self.assertEqual(out.returncode, 0, out.stderr)
        st = self.status_file()
        self.assertEqual((st["state"], st["question"], st["summary"]), ("running", None, "operator answered: public"))
        self.assertTrue(self.comments(10)[-1].startswith("Operator decision.\n\n> Public or sign-in?"))
        self.assertTrue(self.comments(10)[-1].endswith("\n\npublic"))
        decisions = self.repo / ".git" / "drive-spec" / "spec-10" / "decisions.md"
        self.assertIn("Answer: public", decisions.read_text())
        out = self.run_ds("start", "10", "11")
        self.assertIn(f"`{decisions}` holds each answer, and it overrides the issue where they differ. Match",
                      out.stdout)

    def test_answered_needs_an_open_question(self):
        out = self.run_ds("answered", "10", "public")
        self.assertEqual(out.returncode, 2)
        self.assertEqual(self.comments(10), [])

    def test_no_block_goes_on(self):
        self.run_ds("start", "10", "11")
        self.run_ds("ask", "10", "Kept CSV as the format; revisit?", "--no-block")
        st = self.status_file()
        self.assertEqual((st["state"], st["step"], st["question_blocking"]), ("running", "build", False))

    def test_brief_without_decisions_reads_as_before(self):
        out = self.run_ds("start", "10", "11")
        self.assertIn("explore only past what they cover. Match the repo's", out.stdout)


if __name__ == "__main__":
    unittest.main()
