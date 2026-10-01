"""Authenticated Steam web session for read-only Market History access.

The acquisition detector needs *authenticated* Steam Community Market
History for the monitored account. The unauthenticated endpoint answers
``total_count: 0`` even for accounts that own the market history, which is
why an unauthenticated detector can only ever produce UNKNOWN lots.

This module supplies the authentication layer ONLY. It loads an existing
Steam web session cookie from a runtime secret file and attaches it to a
``requests.Session``. It performs no trading, no listing, and no inventory
mutation, and it never writes credentials anywhere.

Security contract
-----------------
- The cookie value is read from a file mounted read-only by the runtime
  (Docker secret / bind mount), never from source code, Git, SQLite, an
  environment variable, or an HTTP response.
- The cookie value is never logged, never included in exception messages,
  and never returned by any accessor.
- Absent, unreadable, or malformed secrets are not fatal: the caller keeps
  an anonymous session and acquisition detection degrades to the existing
  safe UNKNOWN path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

import requests

#: Default location of the runtime secret, mirroring the existing
#: ``ASF_PASSWORD_FILE`` convention used for the ASF IPC password.
DEFAULT_SESSION_FILE = "/run/secrets/steam_market_session"

#: Environment variable that may point the loader at a different file.
SESSION_FILE_ENV = "STEAM_MARKET_SESSION_FILE"

#: Cookie name required for authenticated Market History.
REQUIRED_COOKIE = "steamLoginSecure"

#: Cookies that Steam's web UI expects alongside ``steamLoginSecure``.
#: Optional — they are applied when present but are not required.
OPTIONAL_COOKIES = ("sessionid", "steamMachineAuth")

REDACTED = "<redacted>"


class SteamWebSessionError(RuntimeError):
    """Raised only for operator-actionable configuration problems.

    Messages must never embed cookie material.
    """


@dataclass(frozen=True)
class SteamWebSessionStatus:
    """Non-secret result of applying a Steam web session.

    Deliberately exposes only whether a session is present and which
    cookie *names* were applied — never any cookie value.
    """

    authenticated: bool
    source: str
    applied_cookie_names: tuple[str, ...]
    missing_required_cookie: bool

    def as_log_message(self) -> str:
        """Return a log-safe one-line description."""
        if not self.authenticated:
            return f"Steam web session NOT active (source={self.source})"
        names = ",".join(self.applied_cookie_names)
        return (
            f"Steam web session active (source={self.source}, "
            f"cookies={names}, values hidden)"
        )


def _parse_cookie_material(raw: str) -> list[tuple[str, str]]:
    """Parse cookie name/value pairs from a secret file body.

    Accepts either a single cookie-header style line
    (``a=1; b=2``) or one ``name=value`` pair per line. Blank lines and
    ``#`` comments are ignored. Returns a list of (name, value).
    """
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()

    text = raw.replace("\r\n", "\n").replace("\r", "\n")

    # Each logical cookie chunk may be on its own line, or several chunks
    # may share a line as a Cookie: header (name=value; name=value).
    chunks: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        chunks.extend(part.strip() for part in line.split(";") if part.strip())

    for chunk in chunks:
        if "=" not in chunk:
            continue
        name, _, value = chunk.partition("=")
        name = name.strip()
        value = value.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        pairs.append((name, value))

    return pairs


def read_session_cookie_pairs(
    path: Optional[str] = None,
) -> list[tuple[str, str]]:
    """Read cookie pairs from the runtime secret file.

    Args:
        path: Optional explicit file path. When omitted the environment
            variable is consulted, then the default path.

    Returns:
        List of (name, value) pairs. Empty when the file is absent.

    Raises:
        SteamWebSessionError: If the file exists but cannot be read.
            The message contains the path only — never cookie material.
    """
    resolved = path or os.getenv(SESSION_FILE_ENV) or DEFAULT_SESSION_FILE

    if not os.path.isfile(resolved):
        return []

    try:
        with open(resolved, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except OSError as exc:
        raise SteamWebSessionError(
            f"Steam web session secret at {resolved!r} could not be read "
            f"(errno {exc.errno})"
        ) from exc

    if not raw.strip():
        return []

    return _parse_cookie_material(raw)


def apply_steam_web_session(
    target_session: requests.Session,
    path: Optional[str] = None,
) -> SteamWebSessionStatus:
    """Attach an authenticated Steam web session to ``target_session``.

    This function is deliberately non-fatal. If the secret is absent the
    session simply stays anonymous, which makes Market History return no
    events and makes acquisition detection fall back to UNKNOWN.

    Args:
        target_session: The requests session used for Steam Market calls.
        path: Optional override for the secret file path.

    Returns:
        SteamWebSessionStatus describing the outcome without any secret.
    """
    resolved = path or os.getenv(SESSION_FILE_ENV) or DEFAULT_SESSION_FILE

    try:
        pairs = read_session_cookie_pairs(resolved)
    except SteamWebSessionError:
        # Operator-actionable, but not fatal to service startup: the
        # detector degrades safely to UNKNOWN. Raise nothing so that a
        # missing/rotated secret cannot take down the whole service.
        pairs = []

    if not pairs:
        return SteamWebSessionStatus(
            authenticated=False,
            source=resolved,
            applied_cookie_names=(),
            missing_required_cookie=False,
        )

    applied: list[str] = []
    for name, value in pairs:
        target_session.cookies.set(name, value, domain=".steamcommunity.com")
        target_session.cookies.set(name, value, domain="steamcommunity.com")
        applied.append(name)

    has_required = REQUIRED_COOKIE in applied

    return SteamWebSessionStatus(
        authenticated=has_required,
        source=resolved,
        applied_cookie_names=tuple(applied),
        missing_required_cookie=not has_required,
    )


def steam_web_session_authenticated(target_session: requests.Session) -> bool:
    """Return True when the session already carries the required cookie."""
    jar: Mapping[str, str] = target_session.cookies.get_dict()
    return bool(jar.get(REQUIRED_COOKIE))


__all__ = [
    "DEFAULT_SESSION_FILE",
    "SESSION_FILE_ENV",
    "REQUIRED_COOKIE",
    "OPTIONAL_COOKIES",
    "SteamWebSessionError",
    "SteamWebSessionStatus",
    "apply_steam_web_session",
    "read_session_cookie_pairs",
    "steam_web_session_authenticated",
]