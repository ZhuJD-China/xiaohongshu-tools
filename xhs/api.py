"""High-level endpoint wrappers.

Each function owns one API's parameters and response shape, so callers deal
in keywords and note ids rather than header names. Every wrapper returns
plain dicts/lists -- no framework types leak out.
"""

from __future__ import annotations

import time
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
            # The web client sends the literal string "sending" here (a
            # client-side state marker), not an empty string.
            "message_id": "sending",
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

    def search_filter(self, keyword: str) -> dict[str, Any]:
        """Return the filter chips the UI shows above search results.

        These are the server's own grouping ids (sort/date/type), so they
        feed back into ``search_notes`` rather than being decoded locally.
        """
        params = {"keyword": keyword, "search_id": new_search_id()}
        data = self.client.request("search_filter", params=params) or {}
        return {
            "keyword": keyword,
            "items": [
                {
                    "id": f.get("id"),
                    "name": f.get("name") or "",
                    "type": f.get("type") or "",
                    "tags": [
                        t.get("word") or t.get("name") or ""
                        for t in (f.get("filter_tags") or [])
                        if isinstance(t, dict)
                    ],
                    "raw": f,
                }
                for f in (data.get("filters") or [])
            ],
        }

    def search_recommend(self, keyword: str) -> dict[str, Any]:
        """Search autocomplete suggestions.

        The server returns HTTP 200 with ``code=1000`` here -- a normal
        "not an exact-match block" code, not an error. What matters is
        ``success: true``, which is what the client keys off.
        """
        data = self.client.request(
            "search_recommend", params={"keyword": keyword}
        ) or {}
        return {
            "keyword": keyword,
            "items": [
                {
                    "text": s.get("text") or "",
                    "type": s.get("type") or "",
                    "search_type": s.get("search_type") or "",
                    "raw": s,
                }
                for s in (data.get("sug_items") or [])
            ],
            "search_cpl_id": data.get("search_cpl_id") or "",
            "word_request_id": data.get("word_request_id") or "",
        }

    def search_topics(self, keyword: str, *, page: int = 1,
                      page_size: int = 20) -> dict[str, Any]:
        """Search hashtags (``/web_api/*``, creator signature).

        The paging block is nested -- a flat ``{"page": 1, "page_size": 20}``
        gets HTTP 400 because ``page`` must be an object here, unlike the
        note search where both are top-level ints.
        """
        payload = {
            "keyword": keyword,
            "suggest_topic_request": {"title": "", "desc": ""},
            "page": {"page_size": page_size, "page": page},
        }
        data = self.client.request("search_topic", payload=payload) or {}
        return {
            "keyword": keyword,
            "page": page,
            "items": [
                {
                    "id": t.get("id") or "",
                    "name": t.get("name") or "",
                    "link": t.get("link") or "",
                    "view_count": t.get("view_num"),
                    "type": t.get("type") or "",
                    "smart": bool(t.get("smart")),
                    "raw": t,
                }
                for t in (data.get("topic_info_dtos") or [])
                if isinstance(t, dict)
            ],
        }

    def search_users(self, keyword: str, *, page: int = 1,
                     page_size: int = 20) -> dict[str, Any]:
        """Search user accounts (``/web_api/*``, creator signature).

        ``search_id`` here is a millisecond timestamp string -- the note
        search uses an 18-char random id instead. They are not
        interchangeable across the two endpoints.
        """
        payload = {
            "keyword": keyword,
            "search_id": str(int(time.time() * 1000)),
            "page": {"page_size": page_size, "page": page},
        }
        data = self.client.request("search_user", payload=payload) or {}
        users = []
        for u in (data.get("user_info_dtos") or []):
            if not isinstance(u, dict):
                continue
            base = u.get("user_base_dto") or {}
            users.append(
                {
                    "user_id": base.get("user_id") or "",
                    "red_id": base.get("red_id") or "",
                    "nickname": base.get("user_nickname") or "",
                    "desc": base.get("desc") or "",
                    "avatar": base.get("image") or base.get("image_size_large") or "",
                    "fans_total": u.get("fans_total"),
                    "discovery_total": u.get("discovery_total"),
                    "fstatus": u.get("fstatus") or "",
                    "raw": u,
                }
            )
        return {"keyword": keyword, "page": page, "items": users}

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

    def me(self) -> dict[str, Any]:
        """The account the loaded cookie belongs to.

        Cheapest available auth check that also tells you *who* you are:
        ``guest: true`` means the cookie was rejected upstream of any
        endpoint, so every other call would fail anyway.
        """
        data = self.client.request("user_me") or {}
        return {
            "guest": bool(data.get("guest")),
            "user_id": data.get("user_id") or "",
            "nickname": data.get("nickname") or "",
            "red_id": data.get("red_id") or "",
            "desc": data.get("desc") or "",
            "avatar": data.get("imageb") or data.get("images") or "",
            "gender": data.get("gender"),
            "xsec_token": data.get("xsec_token") or "",
            "raw": data,
        }

    def user_profile(self, user_id: str) -> dict[str, Any]:
        """Another account's profile and headline statistics.

        The nested ``basic_info`` block holds identity; the counters are
        top-level. ``user_id`` is the opaque one from a search result --
        ``red_id`` is the human-readable handle and is not accepted here.
        """
        data = self.client.request(
            "user_otherinfo", params={"target_user_id": user_id}
        ) or {}
        basic = data.get("basic_info") or {}
        return {
            "user_id": user_id,
            "nickname": basic.get("nickname") or "",
            "red_id": basic.get("red_id") or "",
            "desc": basic.get("desc") or "",
            "avatar": basic.get("imageb") or basic.get("images") or "",
            "ip_location": basic.get("ip_location") or "",
            "posted": data.get("posted"),
            "collected": data.get("collected"),
            "liked": data.get("liked"),
            "interactions": [
                {
                    "name": i.get("name") or "",
                    "type": i.get("type") or "",
                    "count": i.get("count"),
                }
                for i in (data.get("interactions") or [])
                if isinstance(i, dict)
            ],
            "tags": [t.get("name") for t in (data.get("tags") or []) if isinstance(t, dict)],
            "raw": data,
        }

    # ---- comment --------------------------------------------------------
    def comments(
        self,
        note_id: str,
        *,
        xsec_token: str,
        cursor: str = "",
        top_comment_id: str = "",
    ) -> dict[str, Any]:
        """First-level comments for a note.

        ``xsec_token`` is mandatory: without it the server replies
        461/300031 ("note temporarily unavailable"), which reads like the
        note is gone rather than like a missing parameter. It comes from a
        search hit, a note URL, or ``me()['xsec_token']``.

        Set ``top_comment_id`` to fetch a specific comment's page; for the
        replies *under* one comment use :meth:`sub_comments`.
        """
        if not xsec_token:
            raise ValueError(
                "xsec_token is required for comments -- the server returns "
                "461/300031 without it (pass the token from a search result "
                "or note URL)"
            )
        params = {
            "note_id": note_id,
            "cursor": cursor,
            "top_comment_id": top_comment_id,
            "image_formats": "jpg,webp,avif",
            "xsec_token": xsec_token,
        }
        data = self.client.request("comment_page", params=params) or {}
        return self._comment_page(note_id, data)

    def sub_comments(
        self,
        note_id: str,
        root_comment_id: str,
        *,
        xsec_token: str,
        cursor: str = "",
        num: int = 30,
    ) -> dict[str, Any]:
        """Replies nested under one parent comment.

        Same two mandatory extras as :meth:`comments`. The parent id is the
        ``id`` of a comment from that note, and its
        ``sub_comment_cursor`` (rather than ``""``) continues past the
        first page of replies.
        """
        if not xsec_token:
            raise ValueError(
                "xsec_token is required for sub-comments -- the server "
                "returns 461/300031 without it"
            )
        params = {
            "note_id": note_id,
            "root_comment_id": root_comment_id,
            "num": num,
            "cursor": cursor,
            "image_formats": "jpg,webp,avif",
            "xsec_token": xsec_token,
        }
        data = self.client.request("comment_sub_page", params=params) or {}
        return self._comment_page(note_id, data)

    def _comment_page(self, note_id: str, data: dict) -> dict[str, Any]:
        """Shared shape for comment/page and comment/sub/page."""
        items = [
            self._normalise_comment(c)
            for c in (data.get("comments") or [])
            if isinstance(c, dict)
        ]
        return {
            "note_id": note_id,
            "items": items,
            "next_cursor": data.get("cursor") or "",
            "has_more": bool(data.get("has_more")),
            "xsec_token": data.get("xsec_token") or "",
        }

    @staticmethod
    def _normalise_comment(c: dict) -> dict:
        """Flatten one comment.

        Counters arrive as strings (``"87"``, ``"4"``), not ints. Reply
        children are inline under ``sub_comments`` on comment/page and the
        target sits under ``target_comment`` on sub/page, so both are
        normalised to the same keys.
        """
        user = c.get("user_info") or {}
        subs = c.get("sub_comments")
        target = c.get("target_comment")
        return {
            "id": c.get("id") or "",
            "content": c.get("content") or "",
            "time": c.get("create_time"),
            "like_count": c.get("like_count"),
            "liked": bool(c.get("liked")),
            "ip_location": c.get("ip_location") or "",
            "author": user.get("nickname") or "",
            "author_id": user.get("user_id") or "",
            "avatar": user.get("image") or "",
            "sub_comment_count": c.get("sub_comment_count"),
            "sub_comment_cursor": c.get("sub_comment_cursor") or "",
            "sub_comment_has_more": bool(c.get("sub_comment_has_more")),
            "sub_comments": (
                [XHSApi._normalise_comment(s) for s in subs]
                if isinstance(subs, list) else []
            ),
            "target_comment": (
                XHSApi._normalise_comment(target)
                if isinstance(target, dict) else None
            ),
            "raw": c,
        }

    # ---- status ---------------------------------------------------------
    def status(self) -> dict:
        """Whether the loaded cookie is still accepted."""
        return self.client.status()
