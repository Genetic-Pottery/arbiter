"""Issues GitHub App installation tokens, so boxes never hold the App's private key."""

import base64
import json
import os
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .jsonhttp import HttpError, post_json

# What a box needs to push branches and open pull requests, and nothing more.
PERMISSIONS = {"contents": "write", "pull_requests": "write", "metadata": "read"}

# Tokens last an hour. Hand out a new one once less than this is left, so a
# box that refreshes every 40 minutes never holds one about to expire.
REFRESH_BEFORE = 25 * 60


class TokenIssuer:
    """Mints installation tokens scoped to one repository, and reuses each until it nears expiry."""

    def __init__(
        self,
        app_id: str,
        installation_id: str,
        private_key: str,
        repo: str,
        api_url: str = "https://api.github.com",
        clock: Callable[[], float] = time.time,
    ):
        self.app_id = app_id
        self.installation_id = installation_id
        # Only the repository's name: the installation already fixes the owner.
        self.repo = repo.rsplit("/", 1)[-1]
        self.api_url = api_url.rstrip("/")
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: dict[str, Any] | None = None
        self._expires = 0.0
        # openssl reads the key from a file. Keep it private to this process.
        self._keydir = tempfile.TemporaryDirectory(prefix="arbiter-github-")
        self._key = Path(self._keydir.name) / "app.pem"
        fd = os.open(self._key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(private_key)

    @classmethod
    def from_file(cls, path: Path, repo: str, **kwargs: Any) -> "TokenIssuer":
        """Reads the App from a JSON file holding `app_id`, `installation_id`, and `private_key`."""
        app = json.loads(path.read_text())
        return cls(str(app["app_id"]), str(app["installation_id"]), app["private_key"], repo, **kwargs)

    def close(self) -> None:
        """Deletes the copy of the private key."""
        self._keydir.cleanup()

    def token(self) -> dict[str, Any]:
        """Returns `{token, expires_at}` for the repository. Raises HttpError if GitHub refuses."""
        with self._lock:
            if self._cached is None or self._expires - self._clock() < REFRESH_BEFORE:
                resp = post_json(
                    f"{self.api_url}/app/installations/{self.installation_id}/access_tokens",
                    {"repositories": [self.repo], "permissions": PERMISSIONS},
                    timeout=30,
                    headers={"Authorization": f"Bearer {self._jwt()}", "Accept": "application/vnd.github+json"},
                )
                self._cached = {"token": resp["token"], "expires_at": resp["expires_at"]}
                # Python 3.10's fromisoformat doesn't take a trailing Z.
                self._expires = datetime.fromisoformat(resp["expires_at"].replace("Z", "+00:00")).timestamp()
            return dict(self._cached)

    def _jwt(self) -> str:
        now = int(self._clock())
        # GitHub allows ten minutes; backdate a minute for clock drift.
        claims = {"iat": now - 60, "exp": now + 540, "iss": self.app_id}
        signing_input = f"{_b64url(json.dumps({'alg': 'RS256', 'typ': 'JWT'}))}.{_b64url(json.dumps(claims))}"
        try:
            signature = subprocess.run(
                ["openssl", "dgst", "-sha256", "-sign", str(self._key)],
                input=signing_input.encode(),
                capture_output=True,
                check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError) as e:
            raise HttpError(500, f"can't sign the GitHub App token request with openssl: {e}") from e
        return f"{signing_input}.{_b64url(signature)}"


def _b64url(data: str | bytes) -> str:
    raw = data.encode() if isinstance(data, str) else data
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
