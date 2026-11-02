"""The arbiter service: the registry, the event log, and the routes to each team's box."""

from http.server import ThreadingHTTPServer
from typing import Any

from .events import EventLog
from .github import TokenIssuer
from .jsonhttp import HttpError, JsonHandler, post_json, require
from .registry import Registry


def make_server(
    host: str,
    port: int,
    registry: Registry,
    events: EventLog | None = None,
    github: TokenIssuer | None = None,
) -> ThreadingHTTPServer:
    log = events if events is not None else EventLog()

    def box_for(team: str) -> str:
        url = registry.lookup(team)
        if url is None:
            raise HttpError(404, f"no live box serves team {team!r}")
        return url

    class Handler(JsonHandler):
        def route(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
            if method == "GET" and path == "/teams":
                return {"teams": registry.teams()}
            if method == "POST" and path == "/register":
                team, url = require(body, "team", "url")
                ticket, repo = body.get("ticket"), body.get("repo")
                registry.register(
                    team,
                    url,
                    ticket if isinstance(ticket, str) and ticket else None,
                    repo if isinstance(repo, str) and repo else None,
                )
                return {"ok": True}
            if method == "POST" and path == "/message":
                team, speaker, text = require(body, "team", "speaker", "text")
                reply = post_json(f"{box_for(team)}/message", {"team": team, "speaker": speaker, "text": text})
                return {"team": team, "reply": reply["reply"]}
            if method == "POST" and path == "/dispatch":
                (team,) = require(body, "team")
                ticket = body.get("ticket")
                if not isinstance(ticket, dict) or not ticket.get("key"):
                    raise HttpError(400, "missing field: ticket.key")
                url = box_for(team)
                post_json(f"{url}/dispatch", {"team": team, "ticket": ticket}, timeout=30)
                registry.register(team, url, ticket["key"])
                return {"ok": True, "team": team, "ticket": ticket["key"]}
            if method == "POST" and path == "/events":
                team, ticket, type_ = require(body, "team", "ticket", "type")
                try:
                    event = log.append(team, ticket, type_, str(body.get("body") or ""))
                except ValueError as e:
                    raise HttpError(400, str(e)) from e
                return {"id": event["id"]}
            if method == "GET" and path == "/events":
                return {"events": log.pending()}
            if method == "POST" and path == "/events/ack":
                ids = body.get("ids")
                if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
                    raise HttpError(400, "ids must be a list of event ids")
                log.ack(ids)
                return {"ok": True}
            if method == "POST" and path == "/github-token":
                if github is None:
                    raise HttpError(404, "this arbiter issues no GitHub tokens; start it with --github-app")
                # Only a registered box gets a token. The security groups keep
                # anything else off the network; this keeps it off the token.
                host = self.client_address[0]
                if host not in registry.hosts():
                    raise HttpError(403, f"{host} isn't a registered box")
                # The token reaches the repositories of the box's own teams.
                repos = registry.repos_for(host)
                if not repos:
                    raise HttpError(400, f"no team registered from {host} names a repository")
                return github.token(sorted(repos))
            raise HttpError(404, "not found")

    return ThreadingHTTPServer((host, port), Handler)
