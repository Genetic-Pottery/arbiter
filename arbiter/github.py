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
    """Mints installation tokens scoped to the repositories a box asks for, and reuses each until it nears expiry.

    A box gets only repositories in `repos`, the ones the App's installation
    covers and the arbiter serves. One installation belongs to one owner, so
    every repository must share it.
    """

    def __init__(
        self,
        app_id: str,
        installation_id: str,
        private_key: str,
        repos: list[str],
        api_url: str = "https://api.github.com",
        clock: Callable[[], float] = time.time,
    ):
        owners = {repo.partition("/")[0] for repo in repos}
        if not repos or len(owners) != 1 or any(repo.count("/") != 1 for repo in repos):
            raise ValueError(f"repositories must be OWNER/NAME with one owner, got {repos}")
        self.app_id = app_id
        self.installation_id = installation_id
        self.repos = frozenset(repos)
        self.api_url = api_url.rstrip("/")
        self._clock = clock
        self._lock = threading.Lock()
        # One token per set of repositories, with its expiry.
        self._cached: dict[frozenset[str], tuple[dict[str, Any], float]] = {}
        # openssl reads the key from a file. Keep it private to this process.
        self._keydir = tempfile.TemporaryDirectory(prefix="arbiter-github-")
        self._key = Path(self._keydir.name) / "app.pem"
        fd = os.open(self._key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(private_key)

    @classmethod
    def from_file(cls, path: Path, repos: list[str], **kwargs: Any) -> "TokenIssuer":
        """Reads the App from a JSON file holding `app_id`, `installation_id`, and `private_key`."""
        app = json.loads(path.read_text())
        return cls(str(app["app_id"]), str(app["installation_id"]), app["private_key"], repos, **kwargs)

    def close(self) -> None:
        """Deletes the copy of the private key."""
        self._keydir.cleanup()

    def token(self, repos: list[str]) -> dict[str, Any]:
        """Returns `{token, expires_at, repos}` for `repos`.

        Raises HttpError 403 for a repository the arbiter doesn't serve, and
        HttpError with GitHub's reason if GitHub refuses.
        """
        wanted = frozenset(repos)
        if not wanted:
            raise HttpError(400, "no repositories asked for")
        if wanted - self.repos:
            raise HttpError(403, f"the arbiter doesn't serve {', '.join(sorted(wanted - self.repos))}")
        with self._lock:
            cached = self._cached.get(wanted)
            if cached is None or cached[1] - self._clock() < REFRESH_BEFORE:
                try:
                    resp = post_json(
                        f"{self.api_url}/app/installations/{self.installation_id}/access_tokens",
                        # Only the names: the installation already fixes the owner.
                        {"repositories": sorted(r.partition("/")[2] for r in wanted), "permissions": PERMISSIONS},
                        timeout=30,
                        headers={"Authorization": f"Bearer {self._jwt()}", "Accept": "application/vnd.github+json"},
                    )
                except HttpError as e:
                    raise HttpError(e.status, f"GitHub refused a token for {', '.join(sorted(wanted))}: {e}") from None
                # Python 3.10's fromisoformat doesn't take a trailing Z.
                expires = datetime.fromisoformat(resp["expires_at"].replace("Z", "+00:00")).timestamp()
                cached = ({"token": resp["token"], "expires_at": resp["expires_at"], "repos": sorted(wanted)}, expires)
                self._cached[wanted] = cached
            return dict(cached[0])

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
