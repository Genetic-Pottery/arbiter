import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arbiter import box as box_mod  # noqa: E402
from arbiter import server  # noqa: E402
from arbiter.events import EventLog  # noqa: E402
from arbiter.jsonhttp import HttpError, get_json, post_json  # noqa: E402
from arbiter.registry import Registry  # noqa: E402

FAKE_CLAUDE = [sys.executable, str(ROOT / "tests" / "fake_claude.py")]
MCP_SERVER = ROOT / "plugins" / "arbiter" / "scripts" / "arbiter_mcp.py"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class RegistryTest(unittest.TestCase):
    def test_lookup_returns_registered_url(self) -> None:
        reg = Registry()
        reg.register("ui", "http://box-a")
        self.assertEqual(reg.lookup("ui"), "http://box-a")

    def test_unknown_team_is_none(self) -> None:
        self.assertIsNone(Registry().lookup("ui"))

    def test_entry_expires_without_heartbeat(self) -> None:
        clock = FakeClock()
        reg = Registry(ttl=10, clock=clock)
        reg.register("ui", "http://box-a")
        clock.now = 11
        self.assertIsNone(reg.lookup("ui"))
        self.assertEqual(reg.teams(), {})

    def test_heartbeat_keeps_entry_alive(self) -> None:
        clock = FakeClock()
        reg = Registry(ttl=10, clock=clock)
        reg.register("ui", "http://box-a")
        clock.now = 8
        reg.register("ui", "http://box-a")
        clock.now = 16
        self.assertEqual(reg.lookup("ui"), "http://box-a")

    def test_reregister_moves_team(self) -> None:
        reg = Registry()
        reg.register("ui", "http://box-a")
        reg.register("ui", "http://box-b")
        self.assertEqual(reg.lookup("ui"), "http://box-b")

    def test_teams_reports_ticket(self) -> None:
        reg = Registry()
        reg.register("ui", "http://box-a", "UI-7")
        reg.register("db", "http://box-a")
        self.assertEqual(
            reg.teams(),
            {
                "ui": {"url": "http://box-a", "busy": True, "ticket": "UI-7"},
                "db": {"url": "http://box-a", "busy": False, "ticket": None},
            },
        )


class EventLogTest(unittest.TestCase):
    def test_ack_removes_events(self) -> None:
        log = EventLog()
        a = log.append("DB", "DB-1", "plan", "p")
        b = log.append("DB", "DB-1", "done", "d")
        log.ack([a["id"]])
        self.assertEqual([e["id"] for e in log.pending()], [b["id"]])

    def test_unknown_type_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            EventLog().append("DB", "DB-1", "finished")

    def test_file_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            log = EventLog(path)
            a = log.append("DB", "DB-1", "plan")
            log.append("DB", "DB-1", "done")
            log.ack([a["id"]])
            again = EventLog(path)
            self.assertEqual([e["type"] for e in again.pending()], ["done"])
            self.assertEqual(again.append("DB", "DB-1", "plan")["id"], 3)


class EndToEndTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        teams = {}
        for team in ("UI", "DB"):
            (root / team).mkdir()
            teams[team] = root / team

        self.arbiter = server.make_server("127.0.0.1", 0, Registry())
        self.arbiter_url = f"http://127.0.0.1:{self.arbiter.server_address[1]}"
        self.boxobj = box_mod.Box(teams, self.arbiter_url, claude_cmd=FAKE_CLAUDE, state_dir=root / "state")
        self.box = box_mod.make_server("127.0.0.1", 0, self.boxobj)
        for srv in (self.arbiter, self.box):
            threading.Thread(target=srv.serve_forever, daemon=True).start()

        self.box_url = f"http://127.0.0.1:{self.box.server_address[1]}"
        self.beat()

    def beat(self) -> None:
        stop = threading.Event()
        stop.set()  # Register once, don't loop.
        box_mod.heartbeat(self.box_url, self.boxobj, 0, stop)

    def tearDown(self) -> None:
        for srv in (self.arbiter, self.box):
            srv.shutdown()
            srv.server_close()
        self.tmp.cleanup()

    def say(self, team: str, speaker: str, text: str) -> str:
        return post_json(f"{self.arbiter_url}/message", {"team": team, "speaker": speaker, "text": text})["reply"]

    def dispatch(self, team: str, key: str, title: str = "Add last_name") -> None:
        ticket = {"key": key, "title": title, "description": "d", "comments": [], "target": "main"}
        post_json(f"{self.arbiter_url}/dispatch", {"team": team, "ticket": ticket})

    def wait_for_exit(self, key: str) -> list[dict[str, Any]]:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            events = [e for e in get_json(f"{self.arbiter_url}/events")["events"] if e["ticket"] == key]
            if any(e["type"] == "exited" for e in events):
                return events
            time.sleep(0.05)
        self.fail(f"{key} never exited")

    def test_routes_to_team_workdir(self) -> None:
        self.assertEqual(self.say("UI", "dana", "hi"), "UI:new:[dana] hi")
        self.assertEqual(self.say("DB", "lee", "hi"), "DB:new:[lee] hi")

    def test_second_message_resumes_session(self) -> None:
        self.say("UI", "dana", "one")
        self.assertEqual(self.say("UI", "dana", "two"), "UI:resumed:[dana] two")

    def test_unknown_team_is_404(self) -> None:
        with self.assertRaises(HttpError) as ctx:
            self.say("AUDIO", "dana", "hi")
        self.assertEqual(ctx.exception.status, 404)

    def test_missing_field_is_400(self) -> None:
        with self.assertRaises(HttpError) as ctx:
            post_json(f"{self.arbiter_url}/message", {"team": "UI", "text": "hi"})
        self.assertEqual(ctx.exception.status, 400)

    def test_dispatch_reports_worker_events_then_exit(self) -> None:
        self.dispatch("DB", "DB-1")
        events = self.wait_for_exit("DB-1")
        self.assertEqual([e["type"] for e in events], ["plan", "done", "exited"])
        self.assertEqual(events[0]["body"], "Warlock plan\ntarget: main")
        self.assertEqual(json.loads(events[2]["body"])["returncode"], 0)

    def test_payload_carries_warlock_cli(self) -> None:
        self.boxobj.warlock_cli = Path("/opt/warlock/scripts/warlock.py")
        self.dispatch("DB", "DB-6")
        self.wait_for_exit("DB-6")
        payload = json.loads((self.boxobj.state_dir / "DB-DB-6.json").read_text())
        self.assertEqual(payload["warlock_cli"], "/opt/warlock/scripts/warlock.py")
        self.assertEqual(payload["team"], "DB")

    def test_crash_reports_only_exit(self) -> None:
        self.dispatch("DB", "DB-2", title="crash")
        events = self.wait_for_exit("DB-2")
        self.assertEqual([e["type"] for e in events], ["exited"])
        self.assertEqual(json.loads(events[0]["body"])["returncode"], 1)

    def test_busy_team_refuses_second_ticket_and_messages(self) -> None:
        self.dispatch("DB", "DB-3", title="slow")
        self.assertEqual(get_json(f"{self.arbiter_url}/teams")["teams"]["DB"]["ticket"], "DB-3")
        self.beat()
        self.assertEqual(get_json(f"{self.arbiter_url}/teams")["teams"]["DB"]["ticket"], "DB-3")
        for attempt in (lambda: self.dispatch("DB", "DB-4"), lambda: self.say("DB", "lee", "hi")):
            with self.assertRaises(HttpError) as ctx:
                attempt()
            self.assertEqual(ctx.exception.status, 409)
        self.wait_for_exit("DB-3")
        deadline = time.monotonic() + 5
        while self.boxobj.ticket("DB") is not None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.beat()
        self.assertFalse(get_json(f"{self.arbiter_url}/teams")["teams"]["DB"]["busy"])

    def test_bad_ticket_key_is_400(self) -> None:
        with self.assertRaises(HttpError) as ctx:
            self.dispatch("DB", "../etc")
        self.assertEqual(ctx.exception.status, 400)

    def test_ack_over_http(self) -> None:
        self.dispatch("DB", "DB-5")
        events = self.wait_for_exit("DB-5")
        post_json(f"{self.arbiter_url}/events/ack", {"ids": [e["id"] for e in events]})
        self.assertEqual(get_json(f"{self.arbiter_url}/events")["events"], [])

    def test_watch_prints_once_per_new_batch(self) -> None:
        watch = ROOT / "plugins" / "arbiter" / "scripts" / "watch.py"
        proc = subprocess.Popen(
            [sys.executable, str(watch), "0.05"],
            stdout=subprocess.PIPE,
            text=True,
            env={"ARBITER_URL": self.arbiter_url},
        )
        try:
            self.dispatch("DB", "DB-7")
            first = proc.stdout.readline()
            self.assertIn("DB-7", first)
            self.assertIn("/arbiter:sync", first)
            self.wait_for_exit("DB-7")
            # Later events arrive as later lines; acked ones are never repeated.
            lines = [first]
            while not any("exited" in line for line in lines):
                lines.append(proc.stdout.readline())
            self.assertEqual(sum(line.count("DB-7 plan") for line in lines), 1)
        finally:
            proc.kill()
            proc.wait()
            proc.stdout.close()

    def test_mcp_server_lists_teams_and_tools(self) -> None:
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_teams", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "send", "arguments": {"team": "NOPE", "text": "x"}}},
        ]
        proc = subprocess.run(
            [sys.executable, str(MCP_SERVER)],
            input="".join(json.dumps(m) + "\n" for m in messages),
            capture_output=True,
            text=True,
            env={"ARBITER_URL": self.arbiter_url},
            timeout=10,
        )
        replies = {r["id"]: r for r in map(json.loads, proc.stdout.splitlines())}
        self.assertEqual(sorted(replies), [1, 2, 3, 4])
        self.assertEqual(replies[1]["result"]["serverInfo"]["name"], "arbiter")
        names = {t["name"] for t in replies[2]["result"]["tools"]}
        self.assertEqual(names, {"list_teams", "dispatch", "events", "ack", "send"})
        self.assertEqual(sorted(json.loads(replies[3]["result"]["content"][0]["text"])), ["DB", "UI"])
        self.assertTrue(replies[4]["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
