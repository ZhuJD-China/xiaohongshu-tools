"""HTTP client: signing, headers, retries, and typed error mapping.

Responsibilities kept deliberately narrow -- this layer turns "one API
call" into "one signed request that either returns JSON or raises a
specific error". Endpoint semantics live in ``xhs.api``.
"""

from __future__ import annotations

import time
from typing import Any

import requests

from .config import base_headers, get_endpoint
from .cookies import CookieError, load_cookies
from .sign import sign


class XHSError(RuntimeError):
    """Base for every API-level failure."""

    def __init__(self, message: str, *, code: Any = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


class AuthRequired(XHSError):
    """-101: cookie missing or expired."""


class CaptchaRequired(XHSError):
    """461/471: risk control wants a human to solve a captcha."""


class RateLimited(XHSError):
    """429 / backoff-worthy response."""


class SignatureRejected(XHSError):
    """Server acknowledged receipt but refused the signature."""


# Codes observed from the live API during development.
AUTH_CODES = {-101, -100}
CAPTCHA_STATUSES = {461, 471}


def _classify(status: int, body: dict | None) -> type[XHSError] | None:
    if status in CAPTCHA_STATUSES:
        return CaptchaRequired
    if status == 429:
        return RateLimited
    if body is None:
        return None
    code = body.get("code")
    if code in AUTH_CODES:
        return AuthRequired
    if code in CAPTCHA_STATUSES:
        return CaptchaRequired
    return None


class XHSClient:
    """Signed client bound to one cookie set.

    Parameters
    ----------
    cookies:
        Explicit cookie dict. When omitted, ``cookies.json`` is loaded.
    max_retries:
        Retries for *transient* failures only (429 / 5xx / network). An
        auth or captcha error is never retried: repeating it just deepens
        the risk-control state.
    """

    def __init__(
        self,
        cookies: dict[str, str] | None = None,
        *,
        timeout: float = 20.0,
        max_retries: int = 3,
        allow_unverified: bool = False,
        session: requests.Session | None = None,
    ) -> None:
        self.cookies = cookies if cookies is not None else load_cookies()
        self.timeout = timeout
        self.max_retries = max_retries
        self.allow_unverified = allow_unverified
        self.session = session or requests.Session()
        self.last_status: int | None = None
        self.last_code: Any = None

    # -- low level --------------------------------------------------------
    def request(
        self,
        endpoint: str,
        *,
        params: dict | None = None,
        payload: dict | None = None,
        allow_unverified: bool | None = None,
        referer: str | None = None,
    ) -> Any:
        """Call an endpoint by name and return its ``data`` field.

        Raises a specific XHSError subclass on failure rather than
        returning ``None``: callers should not have to re-derive whether
        an empty result means "no data" or "blocked".
        """
        gate = self.allow_unverified if allow_unverified is None else allow_unverified
        ep = get_endpoint(endpoint, allow_unverified=gate)

        # A POST with no body still needs one for signing consistency.
        body = payload if payload is not None else ({} if ep.method == "POST" else None)

        headers = sign(
            method=ep.method,
            url=ep.url,
            cookies=self.cookies,
            params=params,
            payload=body,
            x_rap=ep.needs_rap,
        )
        headers.update(base_headers(referer or (ep.host + "/")))

        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self._send(ep.method, ep.url, headers, params, body)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise XHSError(f"network error calling {ep.name}: {exc}") from exc
                time.sleep(0.5 * attempt)
                continue

            self.last_status = resp.status_code
            parsed = self._parse(resp, ep.name)

            if resp.status_code in (429,) or resp.status_code >= 500:
                if attempt < self.max_retries:
                    time.sleep(0.8 * attempt)
                    continue

            err = _classify(resp.status_code, parsed)
            if err is not None:
                raise err(
                    self._message(resp, parsed, ep.name),
                    code=(parsed or {}).get("code"),
                    status=resp.status_code,
                )
            if parsed is None:
                raise XHSError(
                    f"{ep.name}: non-JSON response (HTTP {resp.status_code})",
                    status=resp.status_code,
                )
            if not parsed.get("success", True):
                raise SignatureRejected(
                    self._message(resp, parsed, ep.name),
                    code=parsed.get("code"),
                    status=resp.status_code,
                )

            self.last_code = parsed.get("code")
            return parsed.get("data")

    def _send(self, method, url, headers, params, body):
        if method == "POST":
            return self.session.post(
                url,
                params=params,
                json=body,
                headers=headers,
                cookies=self.cookies,
                timeout=self.timeout,
            )
        return self.session.get(
            url,
            params=params,
            headers=headers,
            cookies=self.cookies,
            timeout=self.timeout,
        )

    @staticmethod
    def _parse(resp: requests.Response, name: str) -> dict | None:
        if not resp.content:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _message(resp: requests.Response, parsed: dict | None, name: str) -> str:
        if parsed is not None:
            msg = parsed.get("msg") or parsed.get("message") or ""
            return f"{name}: code={parsed.get('code')} msg={msg}"
        snippet = resp.text.strip()[:160]
        return f"{name}: HTTP {resp.status_code} {snippet}"

    # -- convenience ------------------------------------------------------
    def status(self) -> dict:
        """Cheap probe: does the API consider us authenticated?"""
        from .config import EDITH

        url = EDITH + "/api/sns/web/v1/user/me"
        headers = sign(method="GET", url=url, cookies=self.cookies)
        headers.update(base_headers())
        resp = self.session.get(
            url, headers=headers, cookies=self.cookies, timeout=self.timeout
        )
        self.last_status = resp.status_code
        try:
            body = resp.json()
        except ValueError:
            return {"ok": False, "http": resp.status_code, "reason": "non-JSON"}
        self.last_code = body.get("code")
        return {
            "ok": bool(body.get("success")),
            "http": resp.status_code,
            "code": body.get("code"),
            "msg": body.get("msg"),
        }


__all__ = [
    "XHSClient",
    "XHSError",
    "AuthRequired",
    "CaptchaRequired",
    "RateLimited",
    "SignatureRejected",
    "CookieError",
]
