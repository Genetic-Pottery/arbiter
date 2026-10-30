"""MCP server (stdio) that gives the arbiter session tools to reach the arbiter service.

Standard library only. Reads ARBITER_URL, default http://127.0.0.1:8700.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

ARBITER_URL = os.environ.get("ARBITER_URL", "http://127.0.0.1:8700").rstrip("/")
PROTOCOL_VERSION = "2025-06-18"

TICKET_SCHEMA = {
    "type": "object",
    "description": "Everything the box needs to work the ticket without tracker access.",
    "properties": {
        "key": {"type": "string", "description": "Ticket key, for example DB-12."},
        "title": {"type": "string"},
        "url": {"type": "string"},
        "description": {"type": "string", "description": "The full ticket description, as markdown."},
        "comments": {
            "type": "array",
            "description": "Every comment, oldest first.",
            "items": {
                "type": "object",
                "properties": {"author": {"type": "string"}, "body": {"type": "string"}},
                "required": ["body"],
            },
        },
        "target": {"type": "string", "description": "Branch the pull request merges into."},
        "scope": {"type": "string", "description": "Name of the warlock scope that owns the ticket."},
        "test_plan": {"type": "string"},
    },
    "required": ["key", "title", "description", "comments", "target"],
}

TOOLS = [
    {
        "name": "list_teams",
        "description": "List the teams a live box serves, with each box URL, whether the team is busy, and the key of the ticket it's working. "
        "Teams are independent: teams on the same box work their tickets in parallel, so one busy team never blocks another.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "dispatch",
        "description": "Send a ticket to the box that serves `team`. The box runs /worker:work on it in the background "
        "and reports events. Fails with 409 if the team is busy.",
        "inputSchema": {
            "type": "object",
            "properties": {"team": {"type": "string"}, "ticket": TICKET_SCHEMA},
            "required": ["team", "ticket"],
        },
    },
    {
        "name": "events",
        "description": "Return every event boxes reported that hasn't been acked, oldest first. Types: plan, progress, "
        "paused, halted, done (from the worker) and exited (from the box when the run ends).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "ack",
        "description": "Mark events handled so `events` stops returning them. Ack an event only after its tracker "
        "update succeeded.",
        "inputSchema": {
            "type": "object",
            "properties": {"ids": {"type": "array", "items": {"type": "integer"}}},
            "required": ["ids"],
        },
    },
    {
        "name": "send",
        "description": "Ask a team's box a direct question in its own Claude session. Fails with 409 while the team "
        "is working a ticket.",
        "inputSchema": {
            "type": "object",
            "properties": {"team": {"type": "string"}, "text": {"type": "string"}},
            "required": ["team", "text"],
        },
    },
]


class ToolError(Exception):
    pass


def call_arbiter(method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 600) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{ARBITER_URL}{path}", data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read() or b"{}").get("error", e.reason)
        raise ToolError(f"arbiter returned {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise ToolError(f"can't reach the arbiter at {ARBITER_URL}: {e.reason}") from e


def run_tool(name: str, args: dict[str, Any]) -> Any:
    if name == "list_teams":
        return call_arbiter("GET", "/teams")["teams"]
    if name == "dispatch":
        return call_arbiter("POST", "/dispatch", {"team": args.get("team"), "ticket": args.get("ticket")}, timeout=30)
    if name == "events":
        return call_arbiter("GET", "/events")["events"]
    if name == "ack":
        return call_arbiter("POST", "/events/ack", {"ids": args.get("ids")})
    if name == "send":
        body = {"team": args.get("team"), "speaker": "arbiter", "text": args.get("text")}
        return call_arbiter("POST", "/message", body)["reply"]
    raise ToolError(f"unknown tool {name!r}")


def handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method")
    id_ = msg.get("id")
    if id_ is None:
        return None  # A notification, such as notifications/initialized.
    if method == "initialize":
        version = msg.get("params", {}).get("protocolVersion", PROTOCOL_VERSION)
        result: Any = {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "arbiter", "version": "0.1.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = msg.get("params", {})
        try:
            out = run_tool(params.get("name", ""), params.get("arguments") or {})
            text = out if isinstance(out, str) else json.dumps(out, indent=2)
            result = {"content": [{"type": "text", "text": text}], "isError": False}
        except ToolError as e:
            result = {"content": [{"type": "text", "text": str(e)}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply: dict[str, Any] | None = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            reply = handle(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
