"""Tests for the dispatch script. Run: PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skills/engineering/dispatch

Each test runs `dispatch` as a subprocess in a throwaway git repo, with fake `herdr`, `rex` and `claude` first on PATH.
The fakes answer from per-test JSON fixtures and log their argv; tests assert only on printed lines, exit status,
state files and the logged calls. A class with `mux = "rex"` runs inside a fake Rex instead of a fake herdr, from
fixtures equivalent to herdr's, and expects the same lines."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

DISPATCH = Path(__file__).with_name("dispatch")

FAKE_HERDR = r'''
import json, os, sys
fix = os.environ["FIX"]
args = sys.argv[1:]
with open(os.path.join(fix, "herdr-calls"), "a") as f:
    f.write(json.dumps(args) + "\n")
try:
    with open(os.path.join(fix, "herdr.json")) as f:
        state = json.load(f)
except OSError:
    state = {}
for prefix, message in state.get("fail", {}).items():
    if " ".join(args).startswith(prefix):
        sys.stderr.write(json.dumps({"error": {"message": message}}))
        sys.exit(1)
if args[:2] == ["agent", "list"]:
    print(json.dumps({"result": {"agents": state.get("agents", [])}}))
elif args[:2] == ["tab", "create"]:
    print(json.dumps({"result": {"tab": {"tab_id": "T9"}, "root_pane": {"pane_id": "p9"}}}))
else:
    print("{}")
'''

FAKE_REX = r'''
import json, os, sys
fix = os.environ["FIX"]
args = [a for a in sys.argv[1:] if a != "--autostart=false"]
with open(os.path.join(fix, "rex-calls"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
try:
    with open(os.path.join(fix, "rex.json")) as f:
        state = json.load(f)
except OSError:
    state = {}
sessions = state.get("sessions", [])
if args[:1] == ["events"]:
    # The event stream: logs its pid, exits at once under `"events": "exit"`, else prints, once each, what a CLI
    # client's connect prints once the file `client-event` appears and a block's `program_status_changed` once
    # `event` appears, in the shapes real `rex events --all --json` prints, and stays alive until `events-stop`
    # appears (a cleanup) or its fixture dir goes, so an orphan outlives its watch but not its test.
    import time
    with open(os.path.join(fix, "events-pids"), "a") as f:
        f.write(f"{os.getpid()}\n")
    if state.get("events") == "exit":
        sys.exit(0)
    def session_event(kind, payload):
        return {"type": "session_event", "payload": {"session_id": "S1", "event": {"type": kind, "payload": payload}}}
    lines = {
        "client-event": [{"type": "client_joined", "payload": {"client": {"client_id": "c1"}}},
                         session_event("client_connected", {"client_id": "c1"}),
                         session_event("client_disconnected", {"client_id": "c1"}),
                         {"type": "client_left", "payload": {"client_id": "c1"}}],
        "event": [session_event("block_event", {"block_id": "p1", "name": "program_status_changed",
                                                "payload": {"id": "", "record": {"state": "blocked"}}})],
    }
    sent = set()
    while os.path.isdir(fix) and not os.path.exists(os.path.join(fix, "events-stop")):
        for trigger, out in lines.items():
            if trigger not in sent and os.path.exists(os.path.join(fix, trigger)):
                print("\n".join(json.dumps(l) for l in out), flush=True)
                sent.add(trigger)
        time.sleep(0.05)
    sys.exit(0)
for prefix, message in state.get("fail", {}).items():
    if " ".join(args).startswith(prefix):
        sys.stderr.write(f"Error: {message}\n")
        sys.exit(1)
if args[:2] == ["window", "new"]:
    print(json.dumps({"window_id": "T9", "block_ids": ["p9"], "revision": 1}))
elif args[:4] == ["block", "call", "-b", "p9"] and args[4] == "program_status":
    # The new block's Claude reports its first record on poll `ready_after`, or never when that is null.
    polls = os.path.join(fix, "p9-polls")
    n = (int(open(polls).read()) if os.path.exists(polls) else 0) + 1
    open(polls, "w").write(str(n))
    ready = state.get("ready_after", 1)
    records = [{"state": "idle", "effective_app": "claude-code"}] if ready is not None and n >= ready else []
    print(json.dumps({"records": records}))
elif args == ["ls", "--json"]:
    print(json.dumps({"sessions": [{"session_id": s["session_id"], "label": s["label"]} for s in sessions]}))
elif args[:3] == ["window", "ls", "-s"]:
    print(json.dumps(next((s for s in sessions if s["session_id"] == args[3]), {"windows": []})))
elif args[:2] == ["send", "-b"]:
    open(os.path.join(fix, f"{args[2]}-since-send"), "w").write("0")
    print("{}")
elif args[:3] == ["block", "call", "-b"]:
    block = state.get("blocks", {}).get(args[3])
    if block is None:
        sys.stderr.write(f"Error: block target {args[3]!r} not found\n")
        sys.exit(3)
    polls = os.path.join(fix, f"{args[3]}-since-send")
    if args[4] == "program_status" and "after_send" in block and os.path.exists(polls):
        # After a send, the block's Claude reports the records of `after_send` in turn, the last one for good.
        n = int(open(polls).read())
        open(polls, "w").write(str(n + 1))
        print(json.dumps({"records": block["after_send"][min(n, len(block["after_send"]) - 1)]}))
    else:
        print(json.dumps(block.get(args[4], {})))
else:
    print("{}")
'''

FAKE_CLAUDE = r'''
import os, sys
try:
    with open(os.path.join(os.environ["FIX"], "claude.json")) as f:
        sys.stdout.write(f.read())
except OSError:
    print("[]")
'''


def stamp(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


class DispatchCase(unittest.TestCase):
    mux = "herdr"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dispatch-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for name, body in (("herdr", FAKE_HERDR), ("rex", FAKE_REX), ("claude", FAKE_CLAUDE)):
            (bin_dir / name).write_text(f"#!{sys.executable}\n{body}")
            (bin_dir / name).chmod(0o755)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("HERDR_", "REX_", "DISPATCH_", "CLAUDE_"))}
        inside = dict(HERDR_ENV="1", HERDR_WORKSPACE_ID="W1", HERDR_PANE_ID="p0") if self.mux == "herdr" else \
            dict(REX_SESSION="S1", REX_BLOCK="p0")
        self.env = dict(env, **inside, PATH=f"{bin_dir}:{os.environ['PATH']}", FIX=str(self.tmp),
                        XDG_STATE_HOME=str(self.tmp / "state"), CLAUDE_CONFIG_DIR=str(self.tmp / "claude"),
                        DISPATCH_MUX=self.mux, DISPATCH_MAX_CPU="101", DISPATCH_MAX_MEMORY="101", DISPATCH_MAX_LOAD="9999",
                        GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], env=self.env, check=True)
        self.status = self.repo / ".git" / "drive-spec" / "status"
        self.status.mkdir(parents=True)
        self.state_dir = self.tmp / "state" / "dispatch"
        self.panes = []
        self.rex_sessions = {"S1": {"session_id": "S1", "label": "main", "windows": []}}
        self.blocks = {}
        self.herdr({})
        self.shell("S1")

    def herdr(self, extra):
        (self.tmp / "herdr.json").write_text(json.dumps(dict(extra, agents=self.panes)))

    def rex(self):
        (self.tmp / "rex.json").write_text(json.dumps({"sessions": list(self.rex_sessions.values()),
                                                       "blocks": self.blocks}))

    def window(self, session, tab, label):
        s = self.rex_sessions.setdefault(session, {"session_id": session, "label": session, "windows": []})
        w = next((w for w in s["windows"] if w["window_id"] == tab), None)
        if not w:
            w = {"window_id": tab, "label": label, "layers": [{"kind": "tiled", "blocks": []}]}
            s["windows"].append(w)
        return w

    def shell(self, session, block="b-shell"):
        """A Rex terminal block with no Claude in it, in the repo: not an agent pane."""
        self.window(session, "W-shell", "spec-10 notes")["layers"][0]["blocks"].append(
            {"block_id": block, "label": "shell", "creator_name": "com.superlogical.terminal"})
        self.blocks[block] = {"program_status": {"records": []}, "pwd": {"pwd": f"file://host{self.repo}"},
                              "title": {"title": "drive-spec-10"}}
        self.rex()

    def pane(self, pane_id="p1", status="idle", name="spec-10", tab="T1", session=None, cwd=None, title="",
             rex_session="S1", rex_records=None, pwd=True):
        """One Claude pane, in both the herdr and the Rex fixture. Rex: block `pane_id` labelled `shell` in window
        `tab` labelled `name`, its root claude-code record in state `status`."""
        cwd = str(cwd or self.repo)
        p = {"pane_id": pane_id, "name": name, "terminal_title_stripped": title, "cwd": cwd,
             "agent_status": status, "tab_id": tab}
        if session:
            p["agent_session"] = {"value": session}
        self.panes.append(p)
        self.herdr({})
        self.window(rex_session, tab, name)["layers"][0]["blocks"].append(
            {"block_id": pane_id, "label": "shell", "creator_name": "com.superlogical.terminal"})
        records = rex_records or [{"state": status, "app": "claude-code", "effective_app": "claude-code"}]
        self.blocks[pane_id] = {"program_status": {"records": records}, "title": {"title": title},
                                "process": {"foreground": {"cwd": cwd}}}
        if pwd:
            self.blocks[pane_id]["pwd"] = {"pwd": f"file://host{cwd}"}
        self.rex()

    def sessions(self, *sessions):
        (self.tmp / "claude.json").write_text(json.dumps(list(sessions)))

    def spec(self, n=10, archived=False, **fields):
        if "pane" in fields:
            fields.setdefault("mux", self.mux)
        data = dict({"spec": n, "step": "build", "state": "running", "summary": "landed 0/2",
                     "next": f"/drive-spec {n}", "updated_at": stamp()}, **fields)
        d = self.status / "archive" if archived else self.status
        d.mkdir(exist_ok=True)
        (d / f"spec-{n}.json").write_text(json.dumps(data))

    def queue(self, *specs):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "queue.json").write_text(json.dumps(
            [{"spec": s, "repo": str(self.repo), "reason": "load 9.0 > 8", "queued_at": stamp()} for s in specs]))

    def dispatch(self, *args, **env):
        return subprocess.run([str(DISPATCH), "--repo", str(self.repo), *args], capture_output=True, text=True,
                              env=dict(self.env, **env), timeout=60)

    def ok(self, *args, **env):
        out = self.dispatch(*args, **env)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.splitlines()

    def refused(self, *args, **env):
        out = self.dispatch(*args, **env)
        self.assertEqual(out.returncode, 1, out.stdout)
        return out.stderr.strip()

    def logged(self):
        """Every call the fake multiplexer got, `--autostart=false` dropped."""
        f = self.tmp / f"{self.mux}-calls"
        listed = [json.loads(c) for c in f.read_text().splitlines()] if f.exists() else []
        return [" ".join(a for a in c if a != "--autostart=false") for c in listed]

    def calls(self):
        """The fake multiplexer's calls, bar the listings and block reads every command makes."""
        listing = ("agent list",) if self.mux == "herdr" else ("ls ", "window ls ", "block call ")
        return [c for c in self.logged() if not c.startswith(listing)]

    def saved(self, name):
        return json.loads((self.state_dir / name).read_text())


class Status(DispatchCase):
    """Every `status` scenario, inside herdr; `RexStatus` runs them inside Rex."""

    def test_a_blocked_pane_is_a_dialog(self):
        self.spec(pane="p1")
        self.pane(status="blocked")
        self.assertEqual(self.ok("status"), ["NEEDS YOU", " 10 DIALOG dialog open in spec-10: dispatch open 10"])

    def test_a_blocking_question_asks(self):
        self.spec(state="waiting", question="keep CSV?", question_blocking=True, pane="p1")
        self.pane()
        self.assertEqual(self.ok("status"), ["NEEDS YOU", " 10 ASK question waiting in spec-10: dispatch open 10"])

    def test_a_halt_relays_why_and_resume(self):
        self.spec(state="halted", summary="export test red.", next="/review-fix-pr 101")
        self.assertEqual(self.ok("status"), ["NEEDS YOU", " 10 HALT export test red. → /review-fix-pr 101"])

    def test_a_quiet_running_spec_stalls(self):
        self.spec(updated_at=stamp(20), pane="p1")
        self.pane()
        self.assertEqual(self.ok("status"), ["NEEDS YOU", " 10 STALL quiet 20m at build"])

    def test_a_running_spec_without_pane_or_session_is_gone(self):
        self.spec()
        self.assertEqual(self.ok("status"), ["NEEDS YOU", " 10 GONE no session; last build: landed 0/2"])

    def test_a_pause_relays_resume(self):
        self.spec(state="paused", summary="paused at maxSlices.")
        self.assertEqual(self.ok("status"), ["NEEDS YOU", " 10 PAUSE paused at maxSlices. → /drive-spec 10"])

    def test_done_relays_the_pr(self):
        self.spec(state="done", step="qa-pr", pr_url="https://github.com/acme/app/pull/101")
        self.assertEqual(self.ok("status"), ["NEEDS YOU", " 10 PR https://github.com/acme/app/pull/101"])

    def test_tags_sort_by_urgency(self):
        self.spec(11, state="paused", summary="paused.")
        self.spec(12, state="halted", summary="red.")
        self.spec(13, pane="p1")
        self.pane(status="blocked", name="spec-13")
        self.assertEqual([x.split()[1] for x in self.ok("status")[1:]], ["DIALOG", "HALT", "PAUSE"])

    def test_a_working_spec_is_ok(self):
        self.spec(pane="p1")
        self.pane(status="working")
        self.assertEqual(self.ok("status"), ["OK", " 10 running·build landed 0/2 (working, 0m)"])

    def test_the_head_of_the_queue_is_ready_when_pressure_clears(self):
        self.queue("10", "11")
        self.assertEqual(self.ok("status"), ["QUEUED", " 10 READY queued 0m: load 9.0 > 8",
                                             " 11 queued 0m: load 9.0 > 8"])

    def test_the_queue_waits_under_pressure(self):
        self.queue("10")
        self.assertEqual(self.ok("status", DISPATCH_MAX_LOAD="-1"), ["QUEUED", " 10 queued 0m: load 9.0 > 8"])

    def test_a_landed_spec_reads_from_the_archive(self):
        self.spec(archived=True, state="done", pr_url="https://github.com/acme/app/pull/101")
        self.pane(name="drive-spec-10")
        self.assertEqual(self.ok("status"),
                         ["OK", " 10 PR landed, status archived; dispatch ack 10 closes its tab (idle)"])

    def test_a_pane_with_no_status_file(self):
        self.pane(name="drive-spec-10")
        self.assertEqual(self.ok("status"), ["OK", " 10 no status file (idle); dispatch ack 10 closes its tab"])

    def test_a_pane_outside_the_repo_is_not_joined_by_name(self):
        self.pane(name="drive-spec-10", cwd=self.tmp)
        self.assertEqual(self.ok("status"), ["no specs"])

    def test_a_busy_session_counts_as_live(self):
        self.spec(updated_at=stamp(20), session_id="S1")
        self.sessions({"sessionId": "S1", "cwd": str(self.repo), "name": "drive-spec-10", "status": "busy"})
        self.assertEqual(self.ok("status"), ["OK", " 10 running·build landed 0/2 (busy, 20m)"])

    def test_json_reports_the_live_state_as_mux(self):
        self.spec(pane="p1")
        self.pane(status="working")
        row = json.loads(self.dispatch("status", "--json").stdout)[0]
        self.assertEqual((row["pane"], row["mux"]), ("p1", "working"))
        self.assertNotIn("herdr", row)

    def test_a_pane_titled_with_its_spec_joins(self):
        self.spec()
        self.pane(name="", title="drive-spec-10", status="working")
        self.assertEqual(self.ok("status"), ["OK", " 10 running·build landed 0/2 (working, 0m)"])

    def test_the_status_files_pane_joins_without_a_spec_name(self):
        self.spec(pane="p1", session_id="S1")
        self.pane(name="scratch", status="blocked")
        self.assertEqual(self.ok("status"), ["NEEDS YOU", " 10 DIALOG dialog open in scratch: dispatch open 10"])

    def test_a_pane_of_the_other_multiplexer_is_not_joined(self):
        self.spec(pane="p1", mux="rex" if self.mux == "herdr" else "herdr")
        self.pane(name="scratch", status="working")
        self.assertEqual(self.ok("status"), ["NEEDS YOU", " 10 GONE no session; last build: landed 0/2"])


class RexStatus(Status):
    mux = "rex"

    def test_panes_in_other_sessions_are_seen(self):
        self.spec(pane="p1")
        self.pane(status="blocked", rex_session="S2")
        self.assertEqual(self.ok("status"), ["NEEDS YOU", " 10 DIALOG dialog open in spec-10: dispatch open 10"])

    def test_state_is_the_root_claude_records_not_a_subagents(self):
        self.spec(pane="p1")
        self.pane(rex_records=[{"id": "sub1", "state": "working", "effective_app": "claude-code"},
                               {"state": "blocked", "effective_app": "claude-code"}])
        self.assertEqual(self.ok("status"), ["NEEDS YOU", " 10 DIALOG dialog open in spec-10: dispatch open 10"])

    def test_an_unknown_state_reads_idle(self):
        self.spec(pane="p1", updated_at=stamp(20))
        self.pane(status="error")
        self.assertEqual(self.ok("status"), ["NEEDS YOU", " 10 STALL quiet 20m at build"])

    def test_a_block_without_a_claude_record_is_no_pane(self):
        self.spec(pane="p1")
        self.pane(rex_records=[{"state": "working", "effective_app": "vim"}])
        self.assertEqual(self.ok("status"), ["NEEDS YOU", " 10 GONE no session; last build: landed 0/2"])

    def test_a_block_with_no_pwd_takes_its_process_cwd(self):
        self.pane(name="drive-spec-10", pwd=False)
        self.assertEqual(self.ok("status"), ["OK", " 10 no status file (idle); dispatch ack 10 closes its tab"])


class Legacy(DispatchCase):
    def test_a_herdr_pane_key_joins_inside_herdr(self):
        self.spec(herdr_pane="p1")
        self.pane(name="scratch", status="working")
        self.assertEqual(self.ok("status"), ["OK", " 10 running·build landed 0/2 (working, 0m)"])

    def test_a_herdr_pane_key_is_ignored_inside_rex(self):
        self.spec(herdr_pane="p1")
        self.pane(name="scratch", status="working")
        self.assertEqual(self.ok("status", DISPATCH_MUX="rex", REX_SESSION="S1"),
                         ["NEEDS YOU", " 10 GONE no session; last build: landed 0/2"])


class Detection(DispatchCase):
    def setUp(self):
        super().setUp()
        self.spec(state="waiting", pane="p1", mux=None)
        self.pane(status="working")
        for k in ("DISPATCH_MUX", "HERDR_ENV", "HERDR_WORKSPACE_ID", "HERDR_PANE_ID"):
            del self.env[k]

    def listed(self):
        return {name for name in ("herdr", "rex") if (self.tmp / f"{name}-calls").exists()}

    def test_inside_rex_uses_rex(self):
        self.assertEqual(self.ok("status", REX_SESSION="S1"), ["OK", " 10 waiting·build landed 0/2 (working, 0m)"])
        self.assertEqual(self.listed(), {"rex"})

    def test_inside_herdr_uses_herdr(self):
        self.assertEqual(self.ok("status", HERDR_ENV="1"), ["OK", " 10 waiting·build landed 0/2 (working, 0m)"])
        self.assertEqual(self.listed(), {"herdr"})

    def test_herdr_wins_inside_both(self):
        self.ok("status", HERDR_ENV="1", REX_SESSION="S1")
        self.assertEqual(self.listed(), {"herdr"})

    def test_the_variable_forces_one(self):
        self.ok("status", DISPATCH_MUX="rex", HERDR_ENV="1", REX_SESSION="S1")
        self.assertEqual(self.listed(), {"rex"})

    def test_outside_both_pane_commands_refuse(self):
        for args in (["launch", "10"], ["open", "10"], ["answer", "10", "yes"], ["ack", "10"],
                     ["recover", "--do", "10=resume"]):
            self.assertEqual(self.refused(*args), f"dispatch {args[0]} refused: not inside herdr or Rex")
        self.assertEqual(self.listed(), set())

    def test_outside_both_status_shows_no_pane(self):
        self.assertEqual(self.ok("status"), ["OK", " 10 waiting·build landed 0/2 (no pane, 0m)"])
        self.assertEqual(self.ok("recover"), ["10 LEAVE? waiting on your answer in its pane"])
        self.assertEqual(self.ok("merges"), ["nothing to note"])

    def test_a_forced_multiplexer_not_present_refuses_pane_commands(self):
        self.assertEqual(self.refused("open", "10", DISPATCH_MUX="rex"),
                         "dispatch open refused: DISPATCH_MUX=rex but not inside Rex (REX_SESSION unset)")
        self.assertEqual(self.refused("ack", "10", DISPATCH_MUX="herdr"),
                         "dispatch ack refused: DISPATCH_MUX=herdr but not inside herdr (HERDR_ENV unset)")

    def test_an_unknown_value_is_rejected(self):
        self.assertEqual(self.refused("status", DISPATCH_MUX="tmux"),
                         "dispatch: DISPATCH_MUX=tmux is not a multiplexer: use herdr or rex")

    def test_watch_runs_outside_both(self):
        self.spec(state="halted", summary="red.")
        proc = subprocess.Popen([str(DISPATCH), "--repo", str(self.repo), "watch"], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, env=self.env)
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        self.assertEqual(proc.stdout.readline().strip(), "10 HALT red. → /drive-spec 10")


class Launch(DispatchCase):
    """Every `launch` scenario, inside herdr; `RexLaunch` runs them inside Rex."""

    def started(self, *claude_args):
        return [f"tab create --workspace W1 --cwd {self.repo} --label spec-10 --no-focus",
                f"agent start spec-10 --kind claude --pane p9 --timeout 90000 -- -n drive-spec-10{''.join(' ' + a for a in claude_args)}",
                "agent prompt spec-10 /drive-spec 10"]

    def prompted(self, pane, text):
        return [f"agent prompt {pane} {text}"]

    def test_starts_a_new_tab(self):
        self.assertEqual(self.ok("launch", "10"), ["10 started in tab T9 (pane p9)"])
        self.assertEqual(self.calls(), self.started())

    def test_skips_a_spec_already_running(self):
        self.spec(pane="p1")
        self.pane(status="working")
        self.assertEqual(self.ok("launch", "10"), ["10 already running in p1"])
        self.assertEqual(self.calls(), [])

    def test_skips_a_spec_blocked_on_a_dialog(self):
        self.spec(pane="p1")
        self.pane(status="blocked")
        self.assertEqual(self.ok("launch", "10"), ["10 already running in p1"])
        self.assertEqual(self.calls(), [])

    def test_skips_a_spec_whose_session_runs_with_no_pane(self):
        self.spec(session_id="S1")
        self.sessions({"sessionId": "S1", "cwd": str(self.repo), "name": "drive-spec-10", "status": "busy"})
        self.assertEqual(self.ok("launch", "10"), ["10 already running in a Claude session with no pane"])
        self.assertEqual(self.calls(), [])

    def test_resumes_an_idle_pane_with_the_runs_next_command(self):
        self.spec(state="halted", summary="red.", next="/review-fix-pr 101", pane="p1")
        self.pane()
        self.assertEqual(self.ok("launch", "10"), ["10 resumed in p1 with /review-fix-pr 101"])
        self.assertEqual(self.calls(), self.prompted("p1", "/review-fix-pr 101"))

    def test_resumes_an_interrupted_idle_pane_with_drive_spec(self):
        self.spec(next="/review-fix-pr 101", pane="p1")
        self.pane()
        self.assertEqual(self.ok("launch", "10"), ["10 resumed in p1 with /drive-spec 10"])
        self.assertEqual(self.calls(), self.prompted("p1", "/drive-spec 10"))

    def test_leaves_a_spec_waiting_on_its_question(self):
        self.spec(state="waiting", question="keep CSV?", question_blocking=True, pane="p1")
        self.pane()
        self.assertEqual(self.ok("launch", "10"), ["10 waiting on its question in p1: dispatch open 10"])
        self.assertEqual(self.calls(), [])

    def test_leaves_a_done_spec(self):
        self.spec(state="done", pane="p1")
        self.pane()
        self.assertEqual(self.ok("launch", "10"), ["10 already done in p1"])
        self.assertEqual(self.calls(), [])

    def test_queues_under_pressure(self):
        out = self.ok("launch", "10", DISPATCH_MAX_LOAD="-1")
        self.assertEqual(len(out), 1)
        self.assertRegex(out[0], r"^10 queued: load \d+\.\d > -1$")
        self.assertEqual([(q["spec"], q["repo"]) for q in self.saved("queue.json")], [("10", str(self.repo))])
        self.assertEqual(self.calls(), [])

    def test_force_starts_under_pressure(self):
        self.queue("10")
        self.assertEqual(self.ok("launch", "10", "--force", DISPATCH_MAX_LOAD="-1"),
                         ["10 started in tab T9 (pane p9) from the queue"])
        self.assertEqual(self.saved("queue.json"), [])

    def test_a_start_dequeues_the_spec(self):
        self.queue("10", "11")
        self.assertEqual(self.ok("launch", "10"), ["10 started in tab T9 (pane p9) from the queue"])
        self.assertEqual([q["spec"] for q in self.saved("queue.json")], ["11"])

    def test_a_failed_start_closes_its_tab(self):
        self.herdr({"fail": {"agent start": "claude did not start"}})
        self.assertEqual(self.ok("launch", "10"), ["10 failed to start: herdr agent start: claude did not start"])
        self.assertEqual(self.calls()[-1], "tab close T9")


class RexLaunch(Launch):
    mux = "rex"

    def started(self, *claude_args):
        return [f"window new -s S1 spec-10 -c {self.repo} --focus=false --json -- "
                f"env CLAUDE_CONFIG_DIR={self.tmp / 'claude'} {self.tmp / 'bin' / 'claude'} -n drive-spec-10{''.join(' ' + a for a in claude_args)}",
                *self.prompted("p9", "/drive-spec 10")]

    def prompted(self, pane, text):
        return [f"send -b {pane} -- {text}", f"send-key -b {pane} enter"]

    def write_rex(self, **extra):
        (self.tmp / "rex.json").write_text(json.dumps(dict(extra, sessions=list(self.rex_sessions.values()),
                                                           blocks=self.blocks)))

    def test_sends_drive_spec_only_once_claude_reports_its_status(self):
        self.write_rex(ready_after=3)
        self.assertEqual(self.ok("launch", "10"), ["10 started in tab T9 (pane p9)"])
        polls = [i for i, c in enumerate(self.logged()) if c == "block call -b p9 program_status"]
        sent = self.logged().index("send -b p9 -- /drive-spec 10")
        self.assertEqual(len(polls), 3)
        self.assertLess(polls[-1], sent)

    def test_without_a_config_dir_starts_claude_bare(self):
        env = dict(self.env)
        del env["CLAUDE_CONFIG_DIR"]
        self.env = env
        self.ok("launch", "10")
        self.assertEqual(self.calls()[0], f"window new -s S1 spec-10 -c {self.repo} --focus=false --json -- "
                                          f"{self.tmp / 'bin' / 'claude'} -n drive-spec-10")

    def test_a_failed_start_closes_its_tab(self):
        self.write_rex(ready_after=None)
        self.assertEqual(self.ok("launch", "10", DISPATCH_READY_SECONDS="1"),
                         ["10 failed to start: Claude not ready in spec-10 after 1 s"])
        self.assertEqual(self.calls(), [self.started()[0], "window close T9"])

    def test_a_failed_send_closes_its_tab(self):
        self.write_rex(fail={"send ": "block not found"})
        self.assertEqual(self.ok("launch", "10"), ["10 failed to start: rex send: block not found"])
        self.assertEqual(self.calls()[-1], "window close T9")

    def test_a_failed_window_closes_nothing(self):
        self.write_rex(fail={"window new": "no such session"})
        self.assertEqual(self.ok("launch", "10"), ["10 failed to start: rex window new: no such session"])
        self.assertEqual(self.calls(), [self.started()[0]])


class Open(DispatchCase):
    """Every `open` scenario, inside herdr; `RexOpen` runs them inside Rex."""

    def focused(self, pane, tab):
        return [f"agent focus {pane}"]

    def fail_focus(self):
        self.herdr({"fail": {"agent focus": "no such pane"}})
        return "herdr agent focus: no such pane"

    def test_focuses_the_specs_pane(self):
        self.spec(pane="p1")
        self.pane()
        self.assertEqual(self.ok("open", "10"), ["10 opened in p1"])
        self.assertEqual(self.calls(), self.focused("p1", "T1"))

    def test_focuses_the_right_pane_among_several(self):
        self.spec(11, pane="p2")
        self.pane("p1", name="spec-10")
        self.pane("p2", name="spec-11", tab="T2")
        self.assertEqual(self.ok("open", "11"), ["11 opened in p2"])
        self.assertEqual(self.calls(), self.focused("p2", "T2"))

    def test_refuses_without_a_pane(self):
        self.spec()
        self.assertEqual(self.refused("open", "10"), "10 not opened: no pane holds its session; recover it first")
        self.assertEqual(self.calls(), [])

    def test_reports_a_failed_focus(self):
        self.spec(pane="p1")
        self.pane()
        message = self.fail_focus()
        self.assertEqual(self.refused("open", "10"), f"10 not opened: {message}")


class RexOpen(Open):
    mux = "rex"

    def focused(self, pane, tab):
        return [f"window focus -s S1 {tab}", f"block focus -s S1 {pane}"]

    def fail_focus(self):
        (self.tmp / "rex.json").write_text(json.dumps({"sessions": list(self.rex_sessions.values()),
                                                       "blocks": self.blocks,
                                                       "fail": {"window focus": "no such window"}}))
        return "rex window focus: no such window"

    def test_focuses_a_pane_in_another_session(self):
        self.spec(pane="p1")
        self.pane(rex_session="S2")
        self.assertEqual(self.ok("open", "10"), ["10 opened in p1"])
        self.assertEqual(self.calls(), ["window focus -s S2 T1", "block focus -s S2 p1"])


class Answer(DispatchCase):
    """Every `answer` scenario, inside herdr; `RexAnswer` runs them inside Rex."""

    def prompted(self, pane, text):
        return [f"agent prompt {pane} {text}"]

    def waiting(self, status="idle"):
        self.spec(state="waiting", question="keep CSV?", question_blocking=True, pane="p1")
        self.pane(status=status)

    def test_prompts_the_pane_quoting_the_question(self):
        self.waiting()
        self.assertEqual(self.ok("answer", "10", "yes,", "keep", "it"), ["10 answered in p1: keep CSV? → yes, keep it"])
        self.assertEqual(self.calls(),
                         self.prompted("p1", "The operator's answer to your question (keep CSV?): yes, keep it"))

    def test_prompts_the_right_pane_among_several(self):
        self.pane("p1", name="spec-10")
        self.spec(11, state="waiting", question="keep CSV?", question_blocking=True, pane="p2")
        self.pane("p2", name="spec-11", tab="T2")
        self.assertEqual(self.ok("answer", "11", "no"), ["11 answered in p2: keep CSV? → no"])
        self.assertEqual(self.calls(), self.prompted("p2", "The operator's answer to your question (keep CSV?): no"))

    def test_refuses_without_a_status_file(self):
        self.pane(name="drive-spec-10")
        self.assertEqual(self.refused("answer", "10", "yes"), "10 not answered: no status file")
        self.assertEqual(self.calls(), [])

    def test_refuses_a_spec_not_waiting(self):
        self.spec(pane="p1")
        self.pane()
        self.assertEqual(self.refused("answer", "10", "yes"),
                         "10 not answered: it is not waiting on a question (running)")
        self.assertEqual(self.calls(), [])

    def test_refuses_a_non_blocking_question(self):
        self.spec(state="waiting", question="keep CSV?", question_blocking=False, pane="p1")
        self.pane()
        self.assertEqual(self.refused("answer", "10", "yes"),
                         "10 not answered: it is not waiting on a question (waiting)")
        self.assertEqual(self.calls(), [])

    def test_refuses_without_a_pane(self):
        self.spec(state="waiting", question="keep CSV?", question_blocking=True)
        self.assertEqual(self.refused("answer", "10", "yes"),
                         "10 not answered: no pane holds its session; recover it first")
        self.assertEqual(self.calls(), [])

    def test_refuses_a_working_pane(self):
        self.waiting("working")
        self.assertEqual(self.refused("answer", "10", "yes"),
                         "10 not answered: it is working; send it once it settles")
        self.assertEqual(self.calls(), [])

    def test_refuses_a_blocked_pane(self):
        self.waiting("blocked")
        self.assertEqual(self.refused("answer", "10", "yes"),
                         "10 not answered: it is blocked; send it once it settles")
        self.assertEqual(self.calls(), [])

    def test_refuses_a_busy_session(self):
        self.waiting()
        self.spec(state="waiting", question="keep CSV?", question_blocking=True, pane="p1", session_id="S1")
        self.sessions({"sessionId": "S1", "cwd": str(self.repo), "name": "drive-spec-10", "status": "busy"})
        self.assertEqual(self.refused("answer", "10", "yes"), "10 not answered: it is busy; send it once it settles")
        self.assertEqual(self.calls(), [])


class RexAnswer(Answer):
    mux = "rex"

    def prompted(self, pane, text):
        return [f"send -b {pane} -- {text}", f"send-key -b {pane} enter"]

    def test_folds_a_multi_line_answer_into_one_prompt(self):
        self.waiting()
        self.ok("answer", "10", "yes,\r\nkeep it\n\nand the header")
        self.assertEqual(self.calls(), self.prompted(
            "p1", "The operator's answer to your question (keep CSV?): yes, keep it and the header"))


class Ack(DispatchCase):
    """Every `ack` scenario, inside herdr; `RexAck` runs them inside Rex."""

    def closed(self, tab):
        return [f"tab close {tab}"]

    def own(self, pane):
        return {"HERDR_PANE_ID": pane}

    def test_closes_a_done_specs_idle_tab(self):
        self.spec(state="done", pane="p1", session_id="S1", updated_at="2026-01-01T00:00:00Z")
        self.pane()
        self.assertEqual(self.ok("ack", "10"), ["10 acked; tab T1 closed, resume with claude --resume S1"])
        self.assertEqual(self.calls(), self.closed("T1"))
        self.assertEqual(self.saved("acked.json"), {"10": "2026-01-01T00:00:00Z"})

    def test_closes_the_right_tab_among_several(self):
        self.pane("p1", name="spec-10")
        self.spec(11, state="done", pane="p2")
        self.pane("p2", name="spec-11", tab="T2")
        self.assertEqual(self.ok("ack", "11"), ["11 acked; tab T2 closed"])
        self.assertEqual(self.calls(), self.closed("T2"))

    def test_keeps_an_active_pane(self):
        self.spec(state="done", pane="p1")
        self.pane(status="working")
        self.assertEqual(self.ok("ack", "10"), ["10 acked; pane p1 kept, still active"])
        self.assertEqual(self.calls(), [])

    def test_never_closes_its_own_pane(self):
        self.spec(state="done", pane="p1")
        self.pane()
        self.assertEqual(self.ok("ack", "10", **self.own("p1")), ["10 acked; pane p1 kept, still active"])
        self.assertEqual(self.calls(), [])

    def test_never_closes_the_tab_it_runs_in(self):
        self.spec(state="done", pane="p1")
        self.pane()
        self.pane("p0", name="dispatcher", tab="T1")
        self.assertEqual(self.ok("ack", "10", **self.own("p0")), ["10 acked; pane p1 kept, still active"])
        self.assertEqual(self.calls(), [])

    def test_keeps_the_pane_of_a_spec_not_done(self):
        self.spec(pane="p1")
        self.pane()
        self.assertEqual(self.ok("ack", "10"), ["10 acked; pane kept, not done"])
        self.assertEqual(self.calls(), [])

    def test_closes_the_tab_of_a_landed_spec(self):
        self.spec(archived=True, state="done", session_id="S1", updated_at="2026-01-01T00:00:00Z")
        self.pane(name="drive-spec-10")
        self.assertEqual(self.ok("ack", "10"), ["10 acked; tab T1 closed, resume with claude --resume S1"])
        self.assertEqual(self.calls(), self.closed("T1"))
        self.assertEqual(self.saved("acked.json"), {"10": "2026-01-01T00:00:00Z"})

    def test_closes_the_tab_of_a_pane_with_no_status_file(self):
        self.pane(name="drive-spec-10")
        self.assertEqual(self.ok("ack", "10"), ["10 acked; tab T1 closed"])
        self.assertEqual(self.calls(), self.closed("T1"))

    def test_refuses_with_neither_status_nor_pane(self):
        self.assertEqual(self.refused("ack", "10"), "10 not acked: no status file, archived or live, and no pane")
        self.assertEqual(self.calls(), [])


class RexAck(Ack):
    mux = "rex"

    def closed(self, tab):
        return [f"window close {tab}"]

    def own(self, pane):
        return {"REX_BLOCK": pane}

    def test_never_closes_the_window_of_its_shell_block(self):
        self.spec(state="done", pane="p1")
        self.pane()
        self.window("S1", "T1", "spec-10")["layers"][0]["blocks"].append(
            {"block_id": "p0", "label": "shell", "creator_name": "com.superlogical.terminal"})
        self.rex()
        self.assertEqual(self.ok("ack", "10"), ["10 acked; pane p1 kept, still active"])
        self.assertEqual(self.calls(), [])


class Recover(DispatchCase):
    """Every `recover` scenario, inside herdr; `RexRecover` runs them inside Rex."""
    prompt_verb = "agent prompt"

    def started(self, *claude_args):
        return Launch.started(self, *claude_args)

    def prompted(self, pane, text):
        return Launch.prompted(self, pane, text)

    def cleared(self, pane):
        return [f"agent prompt {pane} /clear --wait --timeout 30000"]

    def settles(self, pane, *states):
        """The pane's Claude goes through states after the next prompt; herdr's `--wait` does this itself."""

    def fail_prompt(self, message):
        self.herdr({"fail": {"agent prompt": message}})

    def test_proposes_an_action_per_spec(self):
        self.spec(10, pane="p1")
        self.pane()
        self.spec(11, session_id="S1")
        self.spec(12)
        self.spec(13, state="waiting", question="q?", question_blocking=True)
        self.spec(14, state="halted", summary="red.")
        self.spec(15, pane="p2")
        self.pane("p2", status="working", name="spec-15")
        self.assertEqual(self.ok("recover"), [
            "10 RESUME? interrupted at build 0m ago; session back in p1",
            "11 RESUME? interrupted at build 0m ago; reopen its session in a new tab",
            "12 RESTART? interrupted at build 0m ago; no session to reopen",
            "13 LEAVE? waiting on your answer in its pane",
            "14 LEAVE? halted at build: red.",
        ])

    def test_says_a_run_was_cut_off_by_the_reboot(self):
        self.spec(session_id="S1", updated_at="2000-01-01T00:00:00Z")
        out = self.ok("recover")
        self.assertEqual(len(out), 1)
        self.assertRegex(out[0], r"^10 RESUME\? interrupted at build \d+d ago, before the reboot; "
                                 r"reopen its session in a new tab$")

    def test_nothing_to_recover(self):
        self.assertEqual(self.ok("recover"), ["nothing to recover"])

    def test_leave(self):
        self.spec()
        self.assertEqual(self.ok("recover", "--do", "10=leave"), ["10 left alone"])
        self.assertEqual(self.calls(), [])

    def test_resume_in_its_pane(self):
        self.spec(pane="p1")
        self.pane()
        self.assertEqual(self.ok("recover", "--do", "#10=resume"), ["10 resumed in p1"])
        self.assertEqual(self.calls(), self.prompted("p1", "/drive-spec 10"))

    def test_resume_reopens_its_session_in_a_new_tab(self):
        self.spec(session_id="S1")
        self.assertEqual(self.ok("recover", "--do", "10=resume"), ["10 resumed in tab T9 (pane p9)"])
        self.assertEqual(self.calls(), self.started("--resume", "S1"))

    def test_restart_clears_its_pane(self):
        self.spec(pane="p1")
        self.pane()
        self.settles("p1", "working", "idle")
        self.assertEqual(self.ok("recover", "--do", "10=restart"), ["10 restarted fresh in p1"])
        self.assertEqual(self.calls(), [*self.cleared("p1"), *self.prompted("p1", "/drive-spec 10")])

    def test_restart_in_a_new_tab(self):
        self.spec(session_id="S1")
        self.assertEqual(self.ok("recover", "--do", "10=restart"), ["10 restarted in tab T9 (pane p9)"])
        self.assertEqual(self.calls(), self.started())

    def test_reports_a_failed_action(self):
        self.spec(pane="p1")
        self.pane()
        self.fail_prompt("pane gone")
        self.assertEqual(self.ok("recover", "--do", "10=resume"),
                         [f"10 resume failed: {self.mux} {self.prompt_verb}: pane gone"])

    def test_an_unknown_action(self):
        self.spec()
        self.assertEqual(self.ok("recover", "--do", "10=poke"),
                         ["10 unknown action 'poke': use resume, restart or leave"])

    def test_a_restart_whose_clear_never_settles_fails(self):
        self.spec(pane="p1")
        self.pane()
        self.herdr({"fail": {"agent prompt p1 /clear": "timed out after 30000 ms"}})
        self.assertEqual(self.ok("recover", "--do", "10=restart"),
                         ["10 restart failed: herdr agent prompt: timed out after 30000 ms"])
        self.assertNotIn("agent prompt p1 /drive-spec 10", self.calls())


class RexRecover(Recover):
    mux = "rex"
    prompt_verb = "send"

    def started(self, *claude_args):
        return RexLaunch.started(self, *claude_args)

    def prompted(self, pane, text):
        return RexLaunch.prompted(self, pane, text)

    def cleared(self, pane):
        return self.prompted(pane, "/clear")

    def settles(self, pane, *states):
        self.blocks[pane]["after_send"] = [[{"state": s, "effective_app": "claude-code"}] for s in states]
        self.rex()

    def fail_prompt(self, message):
        (self.tmp / "rex.json").write_text(json.dumps({"sessions": list(self.rex_sessions.values()),
                                                       "blocks": self.blocks, "fail": {"send ": message}}))

    def test_restart_waits_for_its_claude_to_settle_after_clear(self):
        self.spec(pane="p1")
        self.pane()
        self.settles("p1", "idle", "working", "working", "idle")
        self.assertEqual(self.ok("recover", "--do", "10=restart"), ["10 restarted fresh in p1"])
        log = self.logged()
        clear, drive = log.index("send-key -b p1 enter"), log.index("send -b p1 -- /drive-spec 10")
        self.assertEqual(log[clear + 1:drive].count("block call -b p1 program_status"), 4)

    def test_a_restart_whose_clear_never_settles_fails(self):
        self.spec(pane="p1")
        self.pane()
        self.settles("p1", "working")
        self.assertEqual(self.ok("recover", "--do", "10=restart", DISPATCH_SETTLE_SECONDS="1"),
                         ["10 restart failed: rex: p1 still working after 1 s"])
        self.assertEqual(self.calls(), self.cleared("p1"))


class Merges(DispatchCase):
    """Every `merges` scenario, inside herdr; `RexMerges` runs them inside Rex."""

    def setUp(self):
        super().setUp()
        origin = self.tmp / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], env=self.env, check=True)
        self.git("remote", "add", "origin", str(origin))
        self.land("a.txt", "Initial commit")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       env=self.env, check=True, capture_output=True)

    def land(self, name, subject):
        (self.repo / name).write_text(subject)
        self.git("add", name)
        self.git("commit", "-q", "-m", subject)
        self.git("push", "-q", "origin", "HEAD:main")

    def test_notes_a_landing_and_archives_the_spec_it_merged(self):
        self.spec(pane="p1")
        self.spec(11, branch="agent/spec-11")
        self.pane()
        self.assertEqual(self.ok("merges"), ["nothing to note"])
        self.land("b.txt", "Merge pull request #5 from michaelloistl/agent/spec-11")
        self.assertEqual(self.ok("merges"), ["noted to 10"])
        self.assertIn("## main advanced: #5 Merge pull request #5", (self.status / "spec-10.inbox.md").read_text())
        self.assertTrue((self.status / "archive" / "spec-11.json").exists())
        self.assertEqual(self.calls(), [])


class RexMerges(Merges):
    mux = "rex"


class Queue(DispatchCase):
    """`admit` and `unqueue`, inside herdr; `RexQueue` runs them inside Rex."""

    def test_admit_is_clear_without_pressure(self):
        out = self.ok("admit")
        self.assertTrue(out[0].startswith("cpu "), out)
        self.assertEqual(out[1:], ["clear"])
        self.assertEqual(self.calls(), [])

    def test_admit_names_the_pressure_that_blocks(self):
        out = self.ok("admit", DISPATCH_MAX_LOAD="-1")
        self.assertTrue(out[1].startswith("blocked: load "), out)

    def test_unqueue_drops_a_queued_spec(self):
        self.queue("10", "11")
        self.assertEqual(self.ok("unqueue", "10"), ["10 unqueued"])
        self.assertEqual([q["spec"] for q in self.saved("queue.json")], ["11"])
        self.assertEqual(self.ok("unqueue", "10"), ["10 was not queued"])
        self.assertEqual(self.calls(), [])


class RexQueue(Queue):
    mux = "rex"


class Watch(DispatchCase):
    def watch(self, **env):
        """A running `dispatch watch`; `next_line(within)` returns its next line, or None after `within` seconds."""
        proc = subprocess.Popen([str(DISPATCH), "--repo", str(self.repo), "watch"], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, env=dict(self.env, **env))
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        lines = []
        threading.Thread(target=lambda: lines.extend(l.strip() for l in proc.stdout), daemon=True).start()

        def next_line(within=10):
            deadline = time.monotonic() + within
            while not lines and time.monotonic() < deadline:
                time.sleep(0.05)
            return lines.pop(0) if lines else None
        proc.next_line = next_line
        return proc

    def test_prints_what_needs_the_operator(self):
        self.spec(state="halted", summary="red.")
        self.assertEqual(self.watch().next_line(), "10 HALT red. → /drive-spec 10")

    def test_wakes_on_a_status_file_write(self):
        self.spec(state="halted", summary="red.")
        watch = self.watch(DISPATCH_TICK_SECONDS="60")
        self.assertEqual(watch.next_line(), "10 HALT red. → /drive-spec 10")
        self.spec(state="paused", summary="over budget.")
        self.assertEqual(watch.next_line(within=10), "10 PAUSE over budget. → /drive-spec 10")

    def test_rereads_on_the_tick(self):
        self.spec(session_id="s-10")
        watch = self.watch(DISPATCH_TICK_SECONDS="1")
        self.assertEqual(watch.next_line(), "10 GONE no session; last build: landed 0/2")
        self.sessions({"sessionId": "s-10", "status": "busy", "cwd": str(self.repo)})
        self.assertRegex(watch.next_line(within=10), r"^10 ok running·build landed 0/2 \(busy, ")


class RexWatch(Watch):
    mux = "rex"

    def setUp(self):
        super().setUp()
        self.addCleanup((self.tmp / "events-stop").touch)

    def streams(self):
        f = self.tmp / "events-pids"
        return [int(p) for p in f.read_text().split()] if f.exists() else []

    def wait_for_stream(self, count=1):
        deadline = time.monotonic() + 10
        while len(self.streams()) < count and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertGreaterEqual(len(self.streams()), count)

    def alive(self, pid):
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        return bool(state) and not state.startswith("Z")

    def test_a_rex_event_wakes_it_before_the_tick(self):
        self.spec(pane="p1")
        self.pane(status="working")
        watch = self.watch(DISPATCH_TICK_SECONDS="30")
        self.wait_for_stream()
        self.blocks["p1"]["program_status"]["records"][0]["state"] = "blocked"
        self.rex()
        self.assertIsNone(watch.next_line(within=3))
        (self.tmp / "event").touch()
        self.assertEqual(watch.next_line(within=10), "10 DIALOG dialog open in spec-10: dispatch open 10")
        self.assertIn("events --all --json", self.logged())

    def test_a_clients_connect_does_not_wake_it(self):
        # Every `rex` call, the watch's own included, prints client events: waking on them would loop.
        self.spec(pane="p1")
        self.pane(status="working")
        watch = self.watch(DISPATCH_TICK_SECONDS="30")
        self.wait_for_stream()
        self.blocks["p1"]["program_status"]["records"][0]["state"] = "blocked"
        self.rex()
        (self.tmp / "client-event").touch()
        self.assertIsNone(watch.next_line(within=4))
        (self.tmp / "event").touch()
        self.assertEqual(watch.next_line(within=10), "10 DIALOG dialog open in spec-10: dispatch open 10")

    def test_a_stream_that_ends_is_restarted_and_status_files_still_wake_it(self):
        (self.tmp / "rex.json").write_text(json.dumps({"sessions": list(self.rex_sessions.values()),
                                                       "blocks": self.blocks, "events": "exit"}))
        self.spec(state="halted", summary="red.")
        watch = self.watch(DISPATCH_TICK_SECONDS="60")
        self.assertEqual(watch.next_line(), "10 HALT red. → /drive-spec 10")
        self.spec(state="paused", summary="over budget.")
        self.assertEqual(watch.next_line(within=10), "10 PAUSE over budget. → /drive-spec 10")
        self.wait_for_stream(count=2)

    def test_runs_without_rex(self):
        (self.tmp / "bin" / "rex").unlink()
        self.spec(state="halted", summary="red.")
        watch = self.watch(DISPATCH_TICK_SECONDS="60")
        self.assertEqual(watch.next_line(), "10 HALT red. → /drive-spec 10")
        self.spec(state="paused", summary="over budget.")
        self.assertEqual(watch.next_line(within=10), "10 PAUSE over budget. → /drive-spec 10")

    def test_runs_on_the_tick_without_rex(self):
        (self.tmp / "bin" / "rex").unlink()
        self.test_rereads_on_the_tick()

    def test_a_superseded_watch_stops_its_stream(self):
        self.spec(state="halted", summary="red.")
        first = self.watch()
        self.assertEqual(first.next_line(), "10 HALT red. → /drive-spec 10")
        self.wait_for_stream()
        stream = self.streams()[0]
        self.assertTrue(self.alive(stream))
        self.watch()
        self.assertEqual(first.next_line(), "watch superseded by a newer one: leave this one stopped")
        first.wait(timeout=10)
        deadline = time.monotonic() + 5
        while self.alive(stream) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertFalse(self.alive(stream))


if __name__ == "__main__":
    unittest.main()
