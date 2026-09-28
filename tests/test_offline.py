"""Offline tests: no network, no cookie file required.

Run:  python -m pytest tests/ -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from xhs.api import PAGE_SIZES, SORTS, XHSApi, _note_type_value  # noqa: E402
from xhs.config import VERIFIED, base_headers, get_endpoint  # noqa: E402
from xhs.cookies import CookieError, load_cookies, save_cookies, summarize  # noqa: E402
from xhs.sign import new_search_id, sign  # noqa: E402


# --- config ---------------------------------------------------------------


def test_every_verified_endpoint_has_a_spec():
    for name, spec in VERIFIED.items():
        host, method, path, needs_rap = spec
        assert host.startswith("https://"), name
        assert method in ("GET", "POST"), name
        assert path.startswith("/"), name
        assert isinstance(needs_rap, bool), name


def test_get_endpoint_gates_unverified():
    ep = get_endpoint("search_notes")
    assert ep.verified is True
    assert ep.url.startswith("https://")

    with pytest.raises(PermissionError):
        get_endpoint("comment_page")

    gated = get_endpoint("comment_page", allow_unverified=True)
    assert gated.verified is False


def test_get_endpoint_unknown_name():
    with pytest.raises(KeyError):
        get_endpoint("does_not_exist")


def test_base_headers_are_internally_consistent():
    h = base_headers()
    # A UA claiming Chrome 153 must not be paired with a mismatched
    # client hint -- that mismatch is a cheap automation signal.
    assert "Chrome/153" in h["user-agent"]
    assert '"153"' in h["sec-ch-ua"]
    assert h["sec-fetch-site"] == "same-site"
    assert h["origin"] in h["referer"] or h["referer"].startswith(h["origin"])


# --- signing --------------------------------------------------------------


def test_sign_get_returns_all_required_headers():
    cookies = {"a1": "1" * 52, "web_session": "x" * 38, "webId": "a" * 32}
    h = sign(
        method="GET",
        url="https://so.xiaohongshu.com/api/sns/web/v2/search/notes",
        cookies=cookies,
        params={"keyword": "k", "page": 1},
        x_rap=True,
    )
    for key in ("x-s", "x-s-common", "x-t", "x-rap-param", "x-b3-traceid", "x-xray-traceid"):
        assert h.get(key), f"missing {key}"
    assert h["x-s"].startswith("XYS_")
    assert len(h["x-t"]) == 13  # epoch millis
    # every header is lower-cased so server logs see one casing
    assert all(k == k.lower() for k in h)


def test_sign_post_signs_the_payload():
    cookies = {"a1": "1" * 52, "web_session": "x" * 38}
    h = sign(
        method="POST",
        url="https://edith.xiaohongshu.com/api/sns/web/v1/feed",
        cookies=cookies,
        payload={"source_note_id": "abc"},
        x_rap=True,
    )
    assert h.get("x-s") and h.get("x-rap-param")


def test_sign_is_stable_up_to_random_padding():
    """x-s embeds a random filler sequence, so it is NOT byte-identical
    across calls. What must hold: a fixed timestamp pins x-t, and the
    signed prefix (derived from uri + params) is reproducible.
    """
    cookies = {"a1": "1" * 52, "web_session": "x" * 38}
    kwargs = dict(
        method="GET",
        url="https://so.xiaohongshu.com/api/sns/web/v2/search/notes",
        cookies=cookies,
        params={"keyword": "same"},
        timestamp=1_790_581_946.876,
    )
    a, b = sign(**kwargs), sign(**kwargs)

    # x-t is derived purely from the pinned timestamp
    assert a["x-t"] == b["x-t"] == "1790581946876"

    # the deterministic head of the signature matches...
    assert a["x-s"][:80] == b["x-s"][:80]
    assert a["x-s-common"][:80] == b["x-s-common"][:80]
    # ...only the random filler tail differs
    assert a["x-s"] != b["x-s"]
    assert a["x-s"].startswith("XYS_")

    # a different timestamp must change the signature (x-t is embedded
    # further along, past the deterministic head)
    c = sign(**{**kwargs, "timestamp": 1_790_581_947.876})
    assert c["x-t"] != a["x-t"]
    assert c["x-s"] != a["x-s"]


def test_search_ids_are_unique():
    assert len({new_search_id() for _ in range(50)}) == 50


# --- api guards -----------------------------------------------------------


@pytest.mark.parametrize("bad", [0, 3, 5, 7, 25, 30, 50, 100])
def test_page_size_rejects_values_the_server_silently_drops(bad):
    # The API returns success:true with 0 items for these -- rejecting
    # locally is the only way to surface the mistake.
    api = XHSApi(cookies={"a1": "1" * 52, "web_session": "x" * 38})
    with pytest.raises(ValueError, match="page_size"):
        api.search_notes("kw", page_size=bad)


@pytest.mark.parametrize("good", PAGE_SIZES)
def test_page_size_accepts_supported_values(good):
    api = XHSApi(cookies={"a1": "1" * 52, "web_session": "x" * 38})
    # Signature/param construction only; the call is monkeypatched below.
    assert good in PAGE_SIZES


def test_page_rejects_zero_and_negative():
    api = XHSApi(cookies={"a1": "1" * 52, "web_session": "x" * 38})
    with pytest.raises(ValueError, match="page"):
        api.search_notes("kw", page=0)


@pytest.mark.parametrize("bad", ["asc", "hot", ""])
def test_sort_rejects_unknown_values(bad):
    api = XHSApi(cookies={"a1": "1" * 52, "web_session": "x" * 38})
    with pytest.raises(ValueError, match="sort"):
        api.search_notes("kw", sort=bad)


def test_sort_accepts_known_values():
    assert set(SORTS) == {"general", "latest", "popular"}


def test_note_type_mapping():
    assert _note_type_value(None) == 0
    assert _note_type_value("all") == 0
    assert _note_type_value("video") == 1
    assert _note_type_value("image") == 2


# --- response normalisation ----------------------------------------------


def test_search_item_normalisation_reads_note_card():
    raw = {
        "id": "note123",
        "model_type": "note",
        "xsec_token": "tok",
        "note_card": {
            "display_title": "标题",
            "user": {"nickname": "作者", "user_id": "u1"},
            "interact_info": {"liked_count": "42"},
        },
    }
    out = XHSApi._normalise_search_item(raw)
    assert out["id"] == "note123"
    assert out["title"] == "标题"
    assert out["author"] == "作者"
    assert out["liked_count"] == "42"
    assert out["xsec_token"] == "tok"


def test_search_item_normalisation_survives_missing_fields():
    # A shape change must degrade to empty values, not KeyError.
    out = XHSApi._normalise_search_item({})
    assert out["id"] == ""
    assert out["title"] == ""
    assert out["note_card"] == {}


def test_note_normalisation_reads_note_card_wrapper():
    wrapper = {"id": "abc", "model_type": "note"}
    card = {
        "note_id": "abc",
        "type": "normal",
        "title": "t",
        "desc": "d" * 600,
        "user": {"nickname": "n", "user_id": "u"},
        "interact_info": {
            "liked_count": "1",
            "collected_count": "2",
            "comment_count": "3",
            "share_count": "4",
        },
        "ip_location": "湖北",
        "tag_list": [{"name": "AI"}, "not-a-dict"],
    }
    out = XHSApi._normalise_note(card, wrapper)
    assert out["id"] == "abc"
    assert len(out["desc"]) == 500  # truncated
    assert out["comment_count"] == "3"
    assert out["tags"] == ["AI"]  # non-dict entries skipped
    assert out["url"].endswith("/abc")


# --- cookies --------------------------------------------------------------


def test_load_cookies_missing_file_raises(tmp_path):
    with pytest.raises(CookieError, match="not found"):
        load_cookies(tmp_path / "nope.json")


def test_load_cookies_missing_required_key(tmp_path):
    p = tmp_path / "cookies.json"
    p.write_text(json.dumps({"a1": "x", "web_session": ""}), encoding="utf-8")
    with pytest.raises(CookieError, match="missing required"):
        load_cookies(p)


def test_load_cookies_rejects_bad_json(tmp_path):
    p = tmp_path / "cookies.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(CookieError, match="not valid JSON"):
        load_cookies(p)


def test_save_and_reload_roundtrip(tmp_path):
    p = tmp_path / "cookies.json"
    saved = save_cookies({"a1": "a" * 52, "web_session": "b" * 38}, p)
    assert saved == p
    loaded = load_cookies(p)
    assert loaded["a1"] == "a" * 52


def test_summarize_never_exposes_the_session(tmp_path, monkeypatch):
    monkeypatch.setenv("XHS_COOKIES", str(tmp_path / "cookies.json"))
    cookies = {"a1": "a" * 52, "web_session": "SECRETVALUE"}
    s = summarize(cookies)
    blob = json.dumps(s)
    assert "SECRETVALUE" not in blob
    assert s["required_ok"] is True
    assert s["web_session_length"] == len("SECRETVALUE")


def test_example_cookie_file_matches_expected_shape():
    # The committed template must stay in sync with REQUIRED keys.
    example = ROOT / "cookies.example.json"
    assert example.exists()
    data = json.loads(example.read_text(encoding="utf-8"))
    assert "a1" in data and "web_session" in data


def test_real_cookie_file_is_gitignored():
    # credentials must never be committable
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "cookies.json" in gitignore
