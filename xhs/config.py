"""Static configuration: hosts, headers, and known API paths.

All paths here were verified against the live web client. Endpoints that
could not be confirmed are marked UNVERIFIED and raise unless explicitly
enabled, so the library never silently returns garbage.
"""

from __future__ import annotations

# --- hosts ---------------------------------------------------------------
WWW = "https://www.xiaohongshu.com"
EDITH = "https://edith.xiaohongshu.com"
SO = "https://so.xiaohongshu.com"

# --- browser identity ----------------------------------------------------
# Kept consistent across every request: a mismatched UA/sec-ch-ua pair is a
# trivially detectable automation signal.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
)
SEC_CH_UA = '"Google Chrome";v="153", "Not_A Brand";v="8", "Chromium";v="153"'
SEC_CH_UA_MOBILE = "?0"
SEC_CH_UA_PLATFORM = '"Windows"'

# --- base headers --------------------------------------------------------
def base_headers(referer: str = WWW + "/") -> dict[str, str]:
    """Headers every request carries, independent of signature."""
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9",
        "origin": WWW,
        "referer": referer,
        "sec-ch-ua": SEC_CH_UA,
        "sec-ch-ua-mobile": SEC_CH_UA_MOBILE,
        "sec-ch-ua-platform": SEC_CH_UA_PLATFORM,
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": USER_AGENT,
    }


# --- API paths -----------------------------------------------------------
# Verified: called successfully with a live cookie during development.
VERIFIED = {
    # POST, so.xiaohongshu.com -- keyword search. Needs x-rap-param.
    "search_notes": (SO, "POST", "/api/sns/web/v2/search/notes", True),
    # POST, edith -- fetch full note detail by id. Needs x-rap-param.
    "note_feed": (EDITH, "POST", "/api/sns/web/v1/feed", True),
    # GET, edith -- notes published by a user.
    "user_posted": (EDITH, "GET", "/api/sns/web/v1/user_posted", False),
}

# Discovered from the web client but not yet exercised end-to-end. Gated so
# an unconfirmed path can't masquerade as a working one.
UNVERIFIED = {
    "comment_page": (EDITH, "GET", "/api/sns/web/v2/comment/page", False),
    "user_profile": (EDITH, "GET", "/api/sns/web/v1/user/me", False),
    "search_user": (SO, "POST", "/api/sns/web/v1/search/user", True),
    "search_topic": (SO, "POST", "/api/sns/web/v1/search/topic", True),
    "home_feed": (EDITH, "POST", "/api/sns/web/v1/homefeed", True),
}


class Endpoint:
    __slots__ = ("name", "host", "method", "path", "needs_rap", "verified")

    def __init__(self, name: str, spec: tuple, verified: bool) -> None:
        self.name = name
        self.host, self.method, self.path, self.needs_rap = spec
        self.verified = verified

    @property
    def url(self) -> str:
        return self.host + self.path

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        flag = "verified" if self.verified else "UNVERIFIED"
        return f"<Endpoint {self.name} {self.method} {self.path} [{flag}]>"


def get_endpoint(name: str, allow_unverified: bool = False) -> Endpoint:
    """Look up an endpoint by name.

    Raises KeyError for unknown names, and PermissionError for an
    unverified path unless *allow_unverified* is set.
    """
    if name in VERIFIED:
        return Endpoint(name, VERIFIED[name], True)
    if name in UNVERIFIED:
        if not allow_unverified:
            raise PermissionError(
                f"endpoint {name!r} is discovered but not verified end-to-end; "
                f"pass allow_unverified=True to try it anyway"
            )
        return Endpoint(name, UNVERIFIED[name], False)
    known = sorted(set(VERIFIED) | set(UNVERIFIED))
    raise KeyError(f"unknown endpoint {name!r}; known: {known}")
