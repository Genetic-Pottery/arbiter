"""Stands in for `claude -p --output-format json` in tests.

For a message, echoes the prompt, the working directory name, and whether the
session was new or resumed. For `/worker:work <payload>`, reports `plan` and
`done` through the worker's emit script, unless the ticket title says to
`crash` (exit 1 without a word) or to be `slow` (wait first).
"""

import json
import subprocess
import sys
import time
from pathlib import Path

EMIT = Path(__file__).resolve().parents[1] / "plugins" / "worker" / "scripts" / "emit.py"

args = sys.argv[1:]
prompt = args[args.index("-p") + 1]

if prompt.startswith("/worker:work "):
    ticket = json.loads(Path(prompt.split(" ", 1)[1]).read_text())
    if "slow" in ticket["title"]:
        time.sleep(1)
    if "crash" in ticket["title"]:
        print("boom", file=sys.stderr)
        sys.exit(1)
    for type_, body in (("plan", f"Warlock plan\ntarget: {ticket['target']}"), ("done", "https://github.com/o/r/pull/1")):
        subprocess.run([sys.executable, str(EMIT), type_, body], check=True, capture_output=True)
    print(json.dumps({"result": "https://github.com/o/r/pull/1"}))
else:
    mode = "new" if "--session-id" in args else "resumed"
    print(json.dumps({"result": f"{Path.cwd().name}:{mode}:{prompt}"}))
