"""Command line: `python -m arbiter serve | box | say | teams | events`."""

import argparse
import json
import shlex
import sys
import threading
from pathlib import Path

from . import box as box_mod
from . import server
from .events import EventLog
from .github import TokenIssuer
from .jsonhttp import HttpError, get_json, post_json
from .registry import Registry

DEFAULT_ARBITER = "http://127.0.0.1:8700"


def parse_team(value: str) -> tuple[str, Path]:
    team, sep, workdir = value.partition("=")
    if not sep or not team or not workdir:
        raise argparse.ArgumentTypeError("expected TEAM=WORKDIR")
    return team, Path(workdir).expanduser().resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arbiter")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("serve", help="run the arbiter service")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8700)
    p.add_argument("--ttl", type=float, default=30.0, help="seconds before a silent box is dropped")
    p.add_argument("--events-file", type=Path, help="JSONL file that keeps unacked events across restarts")
    p.add_argument(
        "--github-app",
        type=Path,
        metavar="FILE",
        help="JSON file with the GitHub App's app_id, installation_id, and private_key; boxes get tokens from it",
    )
    p.add_argument("--github-repo", metavar="OWNER/NAME", help="the one repository tokens reach; required with --github-app")

    p = sub.add_parser("box", help="run a box agent that works tickets for its teams")
    p.add_argument("--arbiter", default=DEFAULT_ARBITER)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8701)
    p.add_argument("--advertise", help="URL the arbiter uses to reach this box (default: http://HOST:PORT)")
    p.add_argument("--team", type=parse_team, action="append", required=True, metavar="TEAM=WORKDIR")
    p.add_argument("--heartbeat", type=float, default=10.0)
    p.add_argument("--claude-args", default="", help="extra flags for every claude run, as one string")
    p.add_argument("--state-dir", type=Path, help="where ticket payloads are written")
    p.add_argument("--warlock-cli", type=Path, help="path to Warlock's scripts/warlock.py; turns on scope checks")
    p.add_argument(
        "--github-repo",
        metavar="OWNER/NAME",
        help="get GitHub access from the arbiter, and clone this repository into missing team directories",
    )
    p.add_argument("--github-refresh", type=float, default=40 * 60, help="seconds between GitHub token refreshes")

    p = sub.add_parser("say", help="send a message through the arbiter")
    p.add_argument("--arbiter", default=DEFAULT_ARBITER)
    p.add_argument("--team", required=True)
    p.add_argument("--speaker", required=True)
    p.add_argument("text")

    p = sub.add_parser("teams", help="list live teams")
    p.add_argument("--arbiter", default=DEFAULT_ARBITER)

    p = sub.add_parser("events", help="print unacked events as JSON")
    p.add_argument("--arbiter", default=DEFAULT_ARBITER)

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        if bool(args.github_app) != bool(args.github_repo):
            parser.error("--github-app and --github-repo go together")
        github = TokenIssuer.from_file(args.github_app, args.github_repo) if args.github_app else None
        srv = server.make_server(args.host, args.port, Registry(ttl=args.ttl), EventLog(args.events_file), github)
        print(f"arbiter listening on http://{args.host}:{args.port}", file=sys.stderr)
        srv.serve_forever()

    elif args.cmd == "box":
        if not args.github_repo:
            for _, workdir in args.team:
                if not workdir.is_dir():
                    parser.error(f"not a directory: {workdir}")
        box = box_mod.Box(
            dict(args.team),
            args.arbiter,
            claude_args=shlex.split(args.claude_args),
            state_dir=args.state_dir,
            warlock_cli=args.warlock_cli,
        )
        srv = box_mod.make_server(args.host, args.port, box)
        url = args.advertise or f"http://{args.host}:{args.port}"
        threading.Thread(
            target=box_mod.heartbeat,
            args=(url, box, args.heartbeat, threading.Event()),
            daemon=True,
        ).start()
        if args.github_repo:
            box.ready.clear()
            threading.Thread(
                target=box_mod.github_login,
                args=(box, args.github_repo, args.github_refresh, threading.Event()),
                daemon=True,
            ).start()
        print(f"box serving {', '.join(box.sessions)} on {url}", file=sys.stderr)
        srv.serve_forever()

    else:
        try:
            if args.cmd == "say":
                resp = post_json(f"{args.arbiter}/message", {"team": args.team, "speaker": args.speaker, "text": args.text})
                print(resp["reply"])
            elif args.cmd == "teams":
                for team, info in sorted(get_json(f"{args.arbiter}/teams")["teams"].items()):
                    print(f"{team}\t{info['url']}\t{info['ticket'] or 'idle'}")
            elif args.cmd == "events":
                print(json.dumps(get_json(f"{args.arbiter}/events")["events"], indent=2))
        except HttpError as e:
            print(f"arbiter: {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
