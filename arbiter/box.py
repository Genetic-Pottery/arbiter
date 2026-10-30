"""The box agent: works tickets for its teams and registers them with the arbiter."""

import json
import os
import re
import shlex
import subprocess
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .jsonhttp import HttpError, JsonHandler, post_json, require

KEY = re.compile(r"^[A-Za-z][A-Za-z0-9]*-\d+$")


@dataclass
class Session:
    team: str
    workdir: Path
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started: bool = False
    # The ticket this team is working, if any. A team works one ticket at a time,
    # and takes no messages meanwhile: both would share one working tree.
    ticket: str | None = None
    # One turn at a time per session; different teams still run in parallel.
    lock: threading.Lock = field(default_factory=threading.Lock)


class Box:
    def __init__(
        self,
        teams: dict[str, Path],
        arbiter_url: str,
        claude_cmd: list[str] | None = None,
        claude_args: list[str] | None = None,
        state_dir: Path | None = None,
        warlock_cli: Path | None = None,
    ):
        self.sessions = {team: Session(team, workdir) for team, workdir in teams.items()}
        self.arbiter_url = arbiter_url
        self.claude_cmd = claude_cmd or shlex.split(os.environ.get("ARBITER_CLAUDE", "claude"))
        self.claude_args = claude_args or []
        self.state_dir = state_dir or Path(tempfile.gettempdir()) / "arbiter-box"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.warlock_cli = warlock_cli

    def _session(self, team: str) -> Session:
        session = self.sessions.get(team)
        if session is None:
            raise HttpError(404, f"this box doesn't serve team {team!r}")
        return session

    def ticket(self, team: str) -> str | None:
        """Returns the ticket `team` is working, or None when it's idle."""
        return self._session(team).ticket

    def ask(self, team: str, speaker: str, text: str) -> str:
        session = self._session(team)
        if session.ticket is not None:
            raise HttpError(409, f"team {team!r} is working {session.ticket}")
        with session.lock:
            resume = ["--resume", session.id] if session.started else ["--session-id", session.id]
            cmd = [*self.claude_cmd, *self.claude_args, "-p", f"[{speaker}] {text}", "--output-format", "json", *resume]
            proc = subprocess.run(cmd, cwd=session.workdir, capture_output=True, text=True)
            if proc.returncode != 0:
                raise HttpError(502, f"claude exited {proc.returncode}: {proc.stderr.strip()}")
            session.started = True
            return json.loads(proc.stdout)["result"]

    def dispatch(self, team: str, ticket: dict[str, Any]) -> None:
        """Starts `/worker:work` on `ticket` in the background. Raises 409 if the team is busy."""
        session = self._session(team)
        key = str(ticket.get("key", ""))
        if not KEY.match(key):
            raise HttpError(400, f"ticket key must look like ABC-123, got {key!r}")
        with session.lock:
            if session.ticket is not None:
                raise HttpError(409, f"team {team!r} is working {session.ticket}")
            session.ticket = key
        payload = self.state_dir / f"{team}-{key}.json"
        # The worker reads settings from the payload, not the environment: a
        # headless run might not be allowed to run the shell command that reads it.
        box_fields: dict[str, Any] = {"team": team}
        if self.warlock_cli is not None:
            box_fields["warlock_cli"] = str(self.warlock_cli)
        payload.write_text(json.dumps({**ticket, **box_fields}, indent=2))
        threading.Thread(target=self._work, args=(session, key, payload), daemon=True).start()

    def _work(self, session: Session, key: str, payload: Path) -> None:
        env = {
            **os.environ,
            "ARBITER_EVENTS_URL": f"{self.arbiter_url}/events",
            "ARBITER_TEAM": session.team,
            "ARBITER_TICKET": key,
        }
        cmd = [*self.claude_cmd, *self.claude_args, "-p", f"/worker:work {payload}", "--output-format", "json"]
        try:
            proc = subprocess.run(cmd, cwd=session.workdir, env=env, capture_output=True, text=True)
            body = json.dumps({"returncode": proc.returncode, "tail": _tail(proc.stdout or proc.stderr)})
        except OSError as e:
            body = json.dumps({"returncode": -1, "tail": str(e)})
        # Report the exit before the heartbeat can say the team is idle, so the
        # arbiter never sees an idle team with the exit still unreported.
        try:
            post_json(f"{self.arbiter_url}/events", {"team": session.team, "ticket": key, "type": "exited", "body": body}, timeout=10)
        except HttpError:
            pass  # No box claims the ticket from here on, so sync treats it as a vanished run.
        finally:
            session.ticket = None


def _tail(text: str, limit: int = 2000) -> str:
    try:
        text = json.loads(text).get("result", text)
    except (json.JSONDecodeError, AttributeError):
        pass
    return text[-limit:]


def make_server(host: str, port: int, box: Box) -> ThreadingHTTPServer:
    class Handler(JsonHandler):
        def route(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
            if method == "POST" and path == "/message":
                team, speaker, text = require(body, "team", "speaker", "text")
                return {"reply": box.ask(team, speaker, text)}
            if method == "POST" and path == "/dispatch":
                (team,) = require(body, "team")
                ticket = body.get("ticket")
                if not isinstance(ticket, dict):
                    raise HttpError(400, "missing field: ticket")
                box.dispatch(team, ticket)
                return {"ok": True}
            raise HttpError(404, "not found")

    return ThreadingHTTPServer((host, port), Handler)


def heartbeat(box_url: str, box: Box, interval: float, stop: threading.Event) -> None:
    """Registers every team with the arbiter, then repeats every `interval` seconds until `stop` is set."""
    while True:
        for team in box.sessions:
            try:
                post_json(
                    f"{box.arbiter_url}/register",
                    {"team": team, "url": box_url, "ticket": box.ticket(team)},
                    timeout=5,
                )
            except HttpError:
                pass  # The arbiter might be restarting; the next beat retries.
        if stop.wait(interval):
            return
