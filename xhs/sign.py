"""Request signing, backed by the vendored ``xhshow`` source.

The xhshow code lives at ``xhs/vendor/xhshow`` and is imported from there,
so this project has no dependency on the published ``xhshow`` package (see
NOTICE.md). It reimplements ``x-s`` / ``x-s-common`` / ``x-rap-param``
offline -- no browser, no CDP, no JS injection. This module only adapts its
interface to ours and keeps every header consistent with the browser
identity in ``config``.
"""

from __future__ import annotations

import time
import uuid

from .vendor.xhshow import Xhshow
from .vendor.xhshow.core.xrap import x_rap_param

_client: Xhshow | None = None


def client() -> Xhshow:
    """Reuse one signer; it holds no per-request state worth resetting."""
    global _client
    if _client is None:
        _client = Xhshow()
    return _client


def new_search_id() -> str:
    return client().get_search_id()


def new_request_id() -> str:
    return client().get_search_request_id()


def new_session_id() -> str:
    """Session id carried in search bodies; plain UUID4 is accepted."""
    return str(uuid.uuid4())


def sign(
    *,
    method: str,
    url: str,
    cookies: dict[str, str],
    params: dict | None = None,
    payload: dict | None = None,
    x_rap: bool = False,
    timestamp: float | None = None,
) -> dict[str, str]:
    """Produce the signature headers for one request.

    GET signs over ``params``; POST signs over ``payload``. Passing the
    wrong one yields a header the server rejects, so the branch is on
    *method* rather than caller intent.

    A single *timestamp* is threaded through every header: XHS rejects
    requests whose ``x-t`` and embedded signature timestamps disagree.
    """
    ts = time.time() if timestamp is None else timestamp
    c = client()
    method = method.upper()
    rap_path = "//" + url.split("://", 1)[-1].split("?", 1)[0]

    if method == "POST":
        headers = c.sign_headers_post(
            uri=url,
            cookies=cookies,
            payload=payload or {},
            x_rap=x_rap,
            timestamp=ts,
        )
    else:
        headers = c.sign_headers_get(
            uri=url,
            cookies=cookies,
            params=params or {},
            timestamp=ts,
        )

    # xhshow emits x-rap-param only for POST; GET endpoints that need it
    # (search) are signed here so both paths stay uniform.
    if x_rap and "x-rap-param" not in headers:
        body = payload if payload is not None else (params or {})
        headers["x-rap-param"] = x_rap_param(rap_path, body)

    # Normalise header casing: requests is case-insensitive but the server
    # logs are not, and mixed casing across a session is an easy tell.
    return {k.lower(): str(v) for k, v in headers.items()}
