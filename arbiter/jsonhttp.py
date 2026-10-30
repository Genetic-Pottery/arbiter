"""Small JSON-over-HTTP helpers shared by the arbiter and the box."""

import json
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler
from typing import Any


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def post_json(
    url: str, body: dict[str, Any], timeout: float = 600.0, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    """POSTs `body` as JSON and returns the decoded response. Raises HttpError on failure."""
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        with e:
            # Our services say "error"; GitHub says "message".
            payload = json.loads(e.read() or b"{}")
            detail = payload.get("error") or payload.get("message") or e.reason
        raise HttpError(e.code, detail) from None
    except urllib.error.URLError as e:
        raise HttpError(502, f"can't reach {url}: {e.reason}") from e


def get_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.URLError as e:
        raise HttpError(502, f"can't reach {url}: {e}") from e


class JsonHandler(BaseHTTPRequestHandler):
    """Base handler: subclasses implement `route(method, path, body)` and return a dict."""

    def route(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        raise HttpError(404, "not found")

    def do_GET(self) -> None:
        self._handle("GET", {})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "body must be JSON"})
            return
        self._handle("POST", body)

    def _handle(self, method: str, body: dict[str, Any]) -> None:
        try:
            self._send(200, self.route(method, self.path, body))
        except HttpError as e:
            self._send(e.status, {"error": str(e)})

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        pass


def require(body: dict[str, Any], *keys: str) -> list[str]:
    """Returns the string values of `keys`, or raises a 400 naming the first missing one."""
    values = []
    for key in keys:
        value = body.get(key)
        if not isinstance(value, str) or not value:
            raise HttpError(400, f"missing field: {key}")
        values.append(value)
    return values
