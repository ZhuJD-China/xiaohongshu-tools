"""Command line interface.

Structured output goes to stdout as JSON so it can be piped; diagnostics go
to stderr. ``--json`` is implied when stdout is not a TTY, which is the
common case when an agent drives this.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .api import SORTS, XHSApi
from .client import XHSError
from .cookies import CookieError, summarize


def _emit(payload: Any, as_json: bool) -> None:
    if as_json:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return
    _render(payload)


def _render(payload: Any, indent: int = 0) -> None:
    pad = "  " * indent
    if isinstance(payload, dict):
        for k, v in payload.items():
            if isinstance(v, (dict, list)) and v:
                print(f"{pad}{k}:")
                _render(v, indent + 1)
            else:
                text = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
                print(f"{pad}{k}: {text[:160]}")
    elif isinstance(payload, list):
        for i, v in enumerate(payload):
            print(f"{pad}[{i}]")
            _render(v, indent + 1)
    else:
        print(f"{pad}{payload}")


def _fail(exc: Exception, as_json: bool) -> int:
    body = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
    if isinstance(exc, XHSError):
        body["code"] = exc.code
        body["http"] = exc.status
    if as_json:
        json.dump(body, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"ERROR [{type(exc).__name__}] {exc}", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="xhs",
        description="Signed access to the Xiaohongshu web API (offline-computed signatures).",
    )
    p.add_argument("--json", action="store_true", help="force JSON output")
    p.add_argument("--no-unverified", action="store_true", help="refuse unverified endpoints (default)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="check whether cookies are still valid")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("search", help="search notes by keyword")
    s.add_argument("keyword")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--page-size", type=int, default=20)
    s.add_argument("--sort", choices=SORTS, default="general")
    s.add_argument("--note-type", choices=["all", "video", "image", "normal"], default=None)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("note", help="fetch one note's detail")
    s.add_argument("note_id")
    s.add_argument("--xsec-token", default="")
    s.set_defaults(func=cmd_note)

    s = sub.add_parser("user-notes", help="list notes published by a user")
    s.add_argument("user_id")
    s.add_argument("--cursor", default="")
    s.add_argument("--num", type=int, default=30)
    s.set_defaults(func=cmd_user_notes)

    s = sub.add_parser("cookies", help="show cookie file status (never prints values)")
    s.set_defaults(func=cmd_cookies)

    return p


def cmd_status(args) -> int:
    api = XHSApi()
    out = api.status()
    out["ok"] = out.get("ok", False)
    _emit(out, args.json)
    return 0 if out["ok"] else 1


def cmd_search(args) -> int:
    api = XHSApi()
    r = api.search_notes(
        args.keyword,
        page=args.page,
        page_size=args.page_size,
        sort=args.sort,
        note_type=args.note_type,
    )
    r["ok"] = True
    _emit(r, args.json)
    return 0


def cmd_note(args) -> int:
    api = XHSApi()
    r = api.get_note(args.note_id, xsec_token=args.xsec_token)
    r["ok"] = r.get("found", False)
    _emit(r, args.json)
    return 0 if r["ok"] else 1


def cmd_user_notes(args) -> int:
    api = XHSApi()
    r = api.user_notes(args.user_id, num=args.num, cursor=args.cursor)
    r["ok"] = True
    _emit(r, args.json)
    return 0


def cmd_cookies(args) -> int:
    try:
        from .cookies import load_cookies

        cookies = load_cookies()
        out = {"ok": True, **summarize(cookies)}
    except CookieError as exc:
        return _fail(exc, args.json)
    _emit(out, args.json)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    as_json = args.json or not sys.stdout.isatty()
    try:
        return args.func(args)
    except (XHSError, CookieError, ValueError) as exc:
        return _fail(exc, as_json)
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
