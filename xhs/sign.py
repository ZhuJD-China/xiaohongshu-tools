"""Request signing via the built-in engine (``xhs.engine``).

The engine computes ``x-s`` / ``x-s-common`` / ``x-rap-param`` entirely
offline inside this package -- no browser, no CDP, no JS injection, no
external signature service. This module adapts that interface to ours and
keeps every header consistent with the browser identity in ``config``.
"""

from __future__ import annotations

import json
import time
import uuid
from urllib.parse import quote, urlparse

from .creator_signing import sign_creator
from .engine import Xhshow
from .engine.core.xrap import x_rap_param

_client: Xhshow | None = None


def client() -> Xhshow:
    """Reuse one signer; it holds no per-request state worth resetting."""
    global _client
    if _client is None:
        _client = Xhshow()
    return _client


def query_url(url: str, params: dict | None) -> str:
    """Append *params* to *url* using the engine's own encoding.

    This must mirror how the signature is computed: the engine signs
    ``quote(value, safe=",")``, leaving `,` literal, while
    ``urlencode``/``quote_plus`` turns it into ``%2C``. Letting the HTTP
    library re-encode the query silently invalidates the signature and the
    server answers 406 -- the URL and the signed string have to agree
    byte for byte.
    """
    if not params:
        return url
    parts = []
    for key, value in params.items():
        if isinstance(value, (list, tuple)):
            raw = ",".join(str(v) for v in value)
        elif value is None:
            raw = ""
        else:
            raw = str(value)
        parts.append(f"{key}={quote(raw, safe=',')}")
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{'&'.join(parts)}"


def json_body(payload: dict) -> str:
    """Serialise a POST body exactly as the browser (and the signature) does.

    Compact separators and unescaped Unicode: the signature is computed over
    this exact string, and the web client sends raw UTF-8 rather than
    ``\\uXXXX`` escapes.
    """
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


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
    signer: str = "main",
) -> dict[str, str]:
    """Produce the signature headers for one request.

    GET signs over ``params``; POST signs over ``payload``. Passing the
    wrong one yields a header the server rejects, so the branch is on
    *method* rather than caller intent.

    A single *timestamp* is threaded through every header: XHS rejects
    requests whose ``x-t`` and embedded signature timestamps disagree.

    ``signer`` picks the scheme and must match the endpoint's path:

    * ``"main"`` -- the ``XYS_`` envelope for ``/api/sns/web/*``.
    * ``"creator"`` -- the ``XYW_`` envelope for ``/web_api/*``, which
      additionally sets an ``appId`` of ``ugc`` and sends only ``x-s`` /
      ``x-t``. These two are not interchangeable: the engine's XYW
      variant uses a different appId and is rejected (HTTP 461) on
      creator paths, so the creator scheme lives in
      ``xhs.creator_signing`` rather than behind a format flag here.
    """
    ts = time.time() if timestamp is None else timestamp
    method = method.upper()

    if signer == "creator":
        # Creator signing hashes only the path (+ JSON body for POST) and
        # emits just x-s / x-t -- no x-s-common, no trace ids. The helper
        # takes no timestamp argument (it stamps internally), so *ts is
        # deliberately not threaded through here.
        sg = sign_creator(
            "url=" + urlparse(url).path,
            payload if method == "POST" else None,
            cookies.get("a1", ""),
        )
        return {k.lower(): str(v) for k, v in sg.items()}

    c = client()
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

    # The engine emits x-rap-param only for POST; GET endpoints that need it
    # (search) are signed here so both paths stay uniform.
    if x_rap and "x-rap-param" not in headers:
        body = payload if payload is not None else (params or {})
        headers["x-rap-param"] = x_rap_param(rap_path, body)

    # Normalise header casing: requests is case-insensitive but the server
    # logs are not, and mixed casing across a session is an easy tell.
    return {k.lower(): str(v) for k, v in headers.items()}
