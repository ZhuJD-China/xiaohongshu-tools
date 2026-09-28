"""Load and save the XHS session cookie.

Cookies live in ``cookies.json`` next to the project root. That file is
listed in ``.gitignore`` -- credentials must never be committed. A
``cookies.example.json`` template is committed instead.

Nothing in this module prints a cookie value: a ``web_session`` in a log
or a transcript is a live account credential.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# cookies.json sits beside the package's parent (project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
COOKIE_PATH = PROJECT_ROOT / "cookies.json"

# Required for any authenticated call. gid/xsecappid improve realism but the
# request still signs without them.
REQUIRED = ("a1", "web_session")
OPTIONAL = ("webId", "gid", "xsecappid", "webBuild", "id_token")


class CookieError(RuntimeError):
    """Raised when usable cookies are missing or malformed."""


def cookie_file() -> Path:
    """Allow overriding the location via XHS_COOKIES (for CI / testing)."""
    env = os.environ.get("XHS_COOKIES")
    return Path(env) if env else COOKIE_PATH


def load_cookies(path: Path | None = None) -> dict[str, str]:
    """Read cookies from disk.

    Raises CookieError when the file is absent or a required key is empty,
    so the caller gets an actionable message instead of a bare -101 from
    the API.
    """
    p = path or cookie_file()
    if not p.exists():
        raise CookieError(
            f"cookie file not found: {p}\n"
            f"copy cookies.example.json to cookies.json and fill it in "
            f"(a1 / web_session at minimum)"
        )
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CookieError(f"cookie file is not valid JSON: {p} ({exc})") from exc
    if not isinstance(data, dict):
        raise CookieError(f"cookie file must be a JSON object: {p}")

    # Drop empties and non-strings; the API treats "" as absent anyway.
    cookies = {
        k: str(v)
        for k, v in data.items()
        if isinstance(v, (str, int, float)) and str(v).strip()
    }

    missing = [k for k in REQUIRED if not cookies.get(k)]
    if missing:
        raise CookieError(
            f"missing required cookie(s) {missing} in {p}\n"
            f"open https://www.xiaohongshu.com/ logged in, then copy a1 and "
            f"web_session from DevTools -> Application -> Cookies"
        )
    return cookies


def save_cookies(cookies: dict[str, Any], path: Path | None = None) -> Path:
    """Persist cookies with owner-only permissions where the OS supports it.

    Windows has no POSIX mode bits, so the chmod is best-effort: it is a
    hardening step, not a guarantee.
    """
    p = path or cookie_file()
    p.write_text(
        json.dumps(cookies, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p


def summarize(cookies: dict[str, str]) -> dict[str, Any]:
    """Status view that never exposes a value."""
    return {
        "path": str(cookie_file()),
        "present": sorted(cookies),
        "required_ok": all(cookies.get(k) for k in REQUIRED),
        "a1_prefix": (cookies.get("a1") or "")[:6] + "...",
        "web_session_length": len(cookies.get("web_session", "")),
    }
