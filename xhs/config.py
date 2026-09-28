"""Static configuration: hosts, headers, and known API paths.

Every path in ``VERIFIED`` has been exercised end-to-end against the live
API with a real cookie. There is no "unverified" tier: a path that has not
proven itself does not belong here, because a wrong path that returns a
plausible-looking error is worse than an absent one.

Endpoint spec: ``(host, method, path, needs_rap, signer)``

* ``signer`` is ``"main"`` for the ``XYS_`` scheme used by the sns/web API,
  and ``"creator"`` for the ``XYW_`` scheme used under ``/web_api/``.
* ``needs_rap`` marks endpoints that also carry ``x-rap-param``.
"""

from __future__ import annotations

# --- hosts ---------------------------------------------------------------
WWW = "https://www.xiaohongshu.com"
EDITH = "https://edith.xiaohongshu.com"
SO = "https://so.xiaohongshu.com"
# /web_api/* paths resolve to EDITH but sign and send creator-origin headers.
CREATOR = "https://creator.xiaohongshu.com"

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
        # Chrome marks XHR as low urgency; omitting it is a small but free
        # tell when compared against a real browser capture.
        "priority": "u=1, i",
    }


# --- API paths -----------------------------------------------------------
# The only correct signing scheme per endpoint; sending the other one is not
# a fallback, it is a rejected request (the engine's XYW variant carries a
# different appId and is refused on creator paths).
MAIN, CREATOR_SIGN = "main", "creator"

# name: (host, method, path, needs_rap, signer)
VERIFIED = {
    # -- search -----------------------------------------------------------
    "search_notes": (SO, "POST", "/api/sns/web/v2/search/notes", True, MAIN),
    "search_filter": (EDITH, "GET", "/api/sns/web/v1/search/filter", False, MAIN),
    "search_recommend": (EDITH, "GET", "/api/sns/web/v1/search/recommend", False, MAIN),
    "search_topic": (EDITH, "POST", "/web_api/sns/v1/search/topic", False, CREATOR_SIGN),
    "search_user": (EDITH, "POST", "/web_api/sns/v1/search/user_info", False, CREATOR_SIGN),
    # -- note -------------------------------------------------------------
    "note_feed": (EDITH, "POST", "/api/sns/web/v1/feed", True, MAIN),
    # -- user -------------------------------------------------------------
    "user_me": (EDITH, "GET", "/api/sns/web/v2/user/me", False, MAIN),
    "user_otherinfo": (EDITH, "GET", "/api/sns/web/v1/user/otherinfo", False, MAIN),
    "user_posted": (EDITH, "GET", "/api/sns/web/v1/user_posted", False, MAIN),
    # -- comment ----------------------------------------------------------
    "comment_page": (EDITH, "GET", "/api/sns/web/v2/comment/page", False, MAIN),
    # Unlike the naive four-parameter form, this one needs the same
    # xsec_token + image_formats as comment/page; without them the server
    # answers 461/300031 ("note temporarily unavailable") rather than 200.
    "comment_sub_page": (
        EDITH, "GET", "/api/sns/web/v2/comment/sub/page", False, MAIN,
    ),
}


class Endpoint:
    __slots__ = ("name", "host", "method", "path", "needs_rap", "signer")

    def __init__(self, name: str, spec: tuple) -> None:
        self.name = name
        self.host, self.method, self.path, self.needs_rap, self.signer = spec

    @property
    def url(self) -> str:
        return self.host + self.path

    @property
    def creator(self) -> bool:
        return self.signer == CREATOR_SIGN

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Endpoint {self.name} {self.method} {self.path} [{self.signer}]>"


def get_endpoint(name: str) -> Endpoint:
    """Look up an endpoint by name.

    Raises ``KeyError`` for an unknown name. The set of known names is
    exactly the set of verified ones, so a typo surfaces immediately instead
    of silently producing a request to a path nobody has confirmed.
    """
    if name in VERIFIED:
        return Endpoint(name, VERIFIED[name])
    raise KeyError(f"unknown endpoint {name!r}; known: {sorted(VERIFIED)}")
