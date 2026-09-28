"""High-level endpoint wrappers.

Each function owns one API's parameters and response shape, so callers deal
in keywords and note ids rather than header names. Every wrapper returns
plain dicts/lists -- no framework types leak out.
"""

from __future__ import annotations

from typing import Any

from .client import XHSClient
from .sign import new_request_id, new_search_id, new_session_id

# Canonical values accepted by the search endpoint.
SORTS = ("general", "latest", "popular")
NOTE_TYPES = ("all", "video", "image", "normal")

# The server accepts only these page sizes. Any other value returns
# success:true with ZERO items and has_more:false -- a silent empty that is
# indistinguishable from "no results", so it is rejected client-side.
PAGE_SIZES = (10, 20)


def _note_type_value(kind: str | None) -> int:
    """Search sends note_type as an int; 'all' -> 0, filters -> 1/2."""
    if kind is None or kind == "all":
        return 0
    if kind == "video":
        return 1
    if kind == "image":
        return 2
    return 0


class XHSApi:
    """Thin façade over :class:`XHSClient` grouped by domain."""

    def __init__(self, client: XHSClient | None = None, **client_kw: Any) -> None:
        self.client = client if client is not None else XHSClient(**client_kw)

    # ---- search ---------------------------------------------------------
    def search_notes(
        self,
        keyword: str,
        *,
        page: int = 1,
        page_size: int = 20,
        sort: str = "general",
        note_type: str | None = None,
    ) -> dict[str, Any]:
        """Search notes.

        Returns ``{"items": [...], "has_more": bool, "page": int}`` where each
        item carries ``id``, ``title``, ``author``, ``liked_count`` and the raw
        ``note_card`` for anything not normalised.

        ``page`` is 1-based to match the UI. ``search_id`` is regenerated per
        call -- reusing one across pages makes the server treat the paging as
        replayed.
        """
        if sort not in SORTS:
            raise ValueError(f"sort must be one of {SORTS}, got {sort!r}")
        if page_size not in PAGE_SIZES:
            raise ValueError(
                f"page_size must be one of {PAGE_SIZES}, got {page_size!r}; "
                f"the server silently returns 0 items for any other value"
            )
        if page < 1:
            raise ValueError(f"page is 1-based, got {page}")

        payload = {
            "keyword": keyword,
            "page": page,
            "page_size": page_size,
            "search_id": new_search_id(),
            "sort": sort,
            "note_type": _note_type_value(note_type),
            "ext_flags": [],
            "geo": "",
            "image_formats": ["jpg", "webp", "avif"],
            "message_id": "",
            "session_id": new_session_id(),
        }

        data = self.client.request("search_notes", payload=payload) or {}
        items = data.get("items") or []

        return {
            "keyword": keyword,
            "page": page,
            "has_more": bool(data.get("has_more")),
            "items": [self._normalise_search_item(i) for i in items],
            "raw_count": len(items),
        }

    @staticmethod
    def _normalise_search_item(item: dict) -> dict:
        """Flatten one search hit.

        Search wraps the note under ``note_card`` and keys it by
        ``model_type``; the id lives at the top level. Reading it defensively
        means a shape change degrades to ``None`` instead of a KeyError.
        """
        card = item.get("note_card") or {}
        user = card.get("user") or {}
        interact = card.get("interact_info") or {}
        return {
            "id": item.get("id") or card.get("note_id") or "",
            "title": card.get("display_title") or card.get("title") or "",
            "type": item.get("model_type") or "note",
            "author": user.get("nickname") or user.get("nick_name") or "",
            "author_id": user.get("user_id") or "",
            "liked_count": interact.get("liked_count"),
            "xsec_token": item.get("xsec_token") or "",
            "note_card": card,
        }

    # ---- note -----------------------------------------------------------
    def get_note(self, note_id: str, *, xsec_token: str = "") -> dict[str, Any]:
        """Fetch one note's full detail (``/feed``).

        ``xsec_token`` comes from a search result or a shared URL; some
        notes require it, and omitting it yields an empty ``data`` rather
        than an error, which is easy to misread as "note does not exist".
        """
        payload: dict[str, Any] = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": "1"},
        }
        if xsec_token:
            payload["xsec_source"] = "xhs_search"
            payload["xsec_token"] = xsec_token

        data = self.client.request("note_feed", payload=payload) or {}
        items = data.get("items") or []
        if not items:
            # /feed reports "not found" as an empty items list with
            # success:true -- easy to misread as a transport failure.
            return {"id": note_id, "found": False, "note": None}

        first = items[0]
        if first.get("ignore"):
            return {"id": note_id, "found": False, "note": None}

        # Actual shape: {"id", "model_type": "note", "note_card": {...}}.
        # The note payload is always under note_card; model_type names the
        # wrapper, it is not itself a key holding the object.
        card = first.get("note_card")
        if not isinstance(card, dict):
            card = first
        return {"id": note_id, "found": True, "note": self._normalise_note(card, first)}

    @staticmethod
    def _normalise_note(note: dict, wrapper: dict) -> dict:
        user = note.get("user") or {}
        interact = note.get("interact_info") or {}
        nid = note.get("note_id") or wrapper.get("id") or ""
        return {
            "id": nid,
            "title": note.get("title") or note.get("display_title") or "",
            "desc": (note.get("desc") or "")[:500],
            "type": note.get("type") or "",
            "author": user.get("nickname") or user.get("nick_name") or "",
            "author_id": user.get("user_id") or "",
            "liked_count": interact.get("liked_count"),
            "collected_count": interact.get("collected_count"),
            "comment_count": interact.get("comment_count"),
            "share_count": interact.get("share_count"),
            "ip_location": note.get("ip_location") or "",
            "time": note.get("time"),
            "tags": [t.get("name") for t in (note.get("tag_list") or []) if isinstance(t, dict)],
            "url": "https://www.xiaohongshu.com/explore/" + nid if nid else "",
            "raw": note,
        }

    # ---- user -----------------------------------------------------------
    def user_notes(
        self,
        user_id: str,
        *,
        num: int = 30,
        cursor: str = "",
    ) -> dict[str, Any]:
        """List notes published by a user.

        ``cursor`` is opaque and returned as ``next_cursor``; feed it back
        verbatim for the next page. An empty ``cursor`` means first page.
        """
        params: dict[str, Any] = {
            "num": num,
            "cursor": cursor,
            "user_id": user_id,
            "image_formats": "jpg,webp,avif",
        }
        data = self.client.request("user_posted", params=params) or {}
        notes = data.get("notes") or []

        return {
            "user_id": user_id,
            "next_cursor": data.get("cursor") or "",
            "total": data.get("total"),
            "items": [
                {
                    "id": n.get("note_id") or "",
                    "title": n.get("display_title") or "",
                    "type": n.get("type") or "",
                    "liked_count": (n.get("interact_info") or {}).get("liked_count"),
                    "raw": n,
                }
                for n in notes
            ],
        }

    # ---- status ---------------------------------------------------------
    def status(self) -> dict:
        """Whether the loaded cookie is still accepted."""
        return self.client.status()
