"""xiaohongshu-tools: signed, offline-computed access to the XHS web API.

Signing is pure Python via ``xhshow`` -- no browser or CDP required. You
supply a session cookie; the library handles headers, retries, and error
classification.

Quickstart::

    from xhs import XHSApi

    api = XHSApi()                    # loads ./cookies.json
    r = api.search_notes("opencode")
    for item in r["items"]:
        print(item["liked_count"], item["title"])
"""

from __future__ import annotations

from .api import XHSApi
from .client import (
    AuthRequired,
    CaptchaRequired,
    RateLimited,
    SignatureRejected,
    XHSClient,
    XHSError,
)
from .cookies import CookieError, cookie_file, load_cookies, save_cookies, summarize

__version__ = "0.1.0"

__all__ = [
    "XHSApi",
    "XHSClient",
    "XHSError",
    "AuthRequired",
    "CaptchaRequired",
    "RateLimited",
    "SignatureRejected",
    "CookieError",
    "load_cookies",
    "save_cookies",
    "summarize",
    "cookie_file",
    "__version__",
]
