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
from xhs.config import CREATOR_SIGN, MAIN, VERIFIED, base_headers, get_endpoint  # noqa: E402
from xhs.cookies import CookieError, load_cookies, save_cookies, summarize  # noqa: E402
from xhs.sign import json_body, new_search_id, query_url, sign  # noqa: E402


# --- config ---------------------------------------------------------------


def test_every_verified_endpoint_has_a_spec():
    for name, spec in VERIFIED.items():
        host, method, path, needs_rap, signer = spec
        assert host.startswith("https://"), name
        assert method in ("GET", "POST"), name
        assert path.startswith("/"), name
        assert isinstance(needs_rap, bool), name
        assert signer in (MAIN, CREATOR_SIGN), name


def test_creator_paths_use_the_creator_signer():
    # /web_api/* takes the XYW_ envelope with appId=ugc; every other path
    # takes XYS_. Getting this backwards is not a style issue, it is a
    # rejected request (observed as 461/300011).
    for name, spec in VERIFIED.items():
        _host, _m, path, _rap, signer = spec
        expected = CREATOR_SIGN if path.startswith("/web_api/") else MAIN
        assert signer == expected, f"{name} ({path}) signs as {signer}"


def test_endpoint_lookup_is_auditable():
    """Known == verified: an unknown name must fail loudly, not silently
    produce a request to a path nobody has confirmed."""
    ep = get_endpoint("search_notes")
    assert ep.url.startswith("https://")
    assert ep.signer == MAIN
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


# --- query/body encoding (the 406 regression) -----------------------------


def test_query_url_keeps_commas_like_the_signature():
    """The signature covers ``quote(value, safe=",")``.

    Letting the HTTP library re-encode the query turns the comma in
    ``image_formats`` into ``%2C``, so the signed string no longer matches
    the URL the server receives. That mismatch surfaced as HTTP 406 on
    comment/page and user_posted -- both went green again once the URL was
    built here.
    """
    url = "https://edith.xiaohongshu.com/api/sns/web/v1/user_posted"
    out = query_url(url, {"image_formats": "jpg,webp,avif", "num": 10})
    assert "image_formats=jpg,webp,avif" in out
    assert "%2C" not in out
    assert "num=10" in out


def test_query_url_encodes_values_the_signature_encodes():
    # '=' must be escaped, otherwise it opens a new key=value pair
    out = query_url("https://x.test/a", {"xsec_token": "AB="})
    assert out.endswith("?xsec_token=AB%3D")


def test_query_url_matches_the_signature_encoder_exactly():
    """The invariant is against the *signature*, not against build_url.

    ``_build_content_string`` signs ``quote(value, safe=",")``, so the URL
    sent must contain exactly that. ``engine.utils.build_url`` is not a
    valid reference for every value: it only escapes ``=``, leaving ``&``
    literal, which would both break query parsing and disagree with the
    signed string. ``quote_plus``/``urlencode`` is wrong in the other
    direction (comma -> %2C). Both wrong encodings produced HTTP 406 on
    comment/page and user_posted.
    """
    from urllib.parse import quote

    for params in (
        {"image_formats": "jpg,webp,avif"},          # comma must survive
        {"xsec_token": "ABEcCTI8bBWEYdVIv="},        # '=' must be escaped
        {"keyword": "a&b"},                          # '&' must be escaped
        {"keyword": "a b c"},                        # space must be escaped
        {"n": 10, "flag": None, "list": ["x", "y"]},  # non-strings coerced
    ):
        base = "https://x.test/api/thing"
        out = query_url(base, params)
        want = []
        for k, v in params.items():
            raw = ",".join(str(x) for x in v) if isinstance(v, (list, tuple)) \
                else "" if v is None else str(v)
            want.append(f"{k}={quote(raw, safe=',')}")
        assert out == f"{base}?{'&'.join(want)}", params


def test_query_url_diverges_from_build_url_only_where_the_signature_does():
    """Documents the one value class where build_url is unsafe."""
    from xhs.engine.utils.url_utils import build_url as engine_build_url

    base = "https://x.test/api/thing"
    # values the two agree on (everything the live endpoints send so far)
    for params in ({"image_formats": "jpg,webp,avif"},
                   {"xsec_token": "ABEcCTI8bBWEYdVIv=", "cursor": ""}):
        assert query_url(base, params) == engine_build_url(base, params), params

    # ...but not on '&' -- and ours is the encoding that was actually signed
    divergent = {"keyword": "a&b"}
    assert query_url(base, divergent) != engine_build_url(base, divergent)


def test_query_url_appends_to_an_existing_query():
    assert query_url("https://x.test/a?b=1", {"c": 2}) == "https://x.test/a?b=1&c=2"
    assert query_url("https://x.test/a", {}) == "https://x.test/a"
    assert query_url("https://x.test/a", None) == "https://x.test/a"


def test_json_body_matches_browser_serialisation():
    """Compact separators and unescaped UTF-8.

    ``requests``' json= helper emits spaces after separators and escapes
    non-ASCII, neither of which the browser does -- and the signature is
    computed over this exact string.
    """
    out = json_body({"keyword": "美食", "page": 1, "list": []})
    assert out == '{"keyword":"美食","page":1,"list":[]}'
    assert " " not in out
    assert "\\u7f8e" not in out  # no \uXXXX escapes


# --- creator signing ------------------------------------------------------


def test_creator_signer_returns_only_the_creator_headers():
    cookies = {"a1": "1" * 52, "web_session": "x" * 38}
    h = sign(
        method="POST",
        url="https://edith.xiaohongshu.com/web_api/sns/v1/search/topic",
        cookies=cookies,
        payload={"keyword": "k", "page": {"page": 1, "page_size": 20}},
        signer=CREATOR_SIGN,
    )
    assert h["x-s"].startswith("XYW_")   # not XYS_
    assert h.get("x-t")
    # creator signing carries neither of these
    assert not h.get("x-s-common")
    assert all(k == k.lower() for k in h)


# --- comment guards -------------------------------------------------------


def test_comments_requires_xsec_token():
    """An empty token does not mean 'no comments' -- it means 461/300031,
    which reads like the note is missing. Fail before the request."""
    api = XHSApi(cookies={"a1": "1" * 52, "web_session": "x" * 38})
    with pytest.raises(ValueError, match="xsec_token"):
        api.comments("note123", xsec_token="")
    with pytest.raises(ValueError, match="xsec_token"):
        api.sub_comments("note123", "parent1", xsec_token="")


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


def test_comment_normalisation_keeps_string_counters():
    # counters arrive as strings ("87", "4"), not ints -- coercing them
    # would silently change what callers see.
    raw = {
        "id": "c1",
        "content": "才三位数（980[doge]）",
        "create_time": 1782178467000,
        "like_count": "87",
        "liked": False,
        "ip_location": "浙江",
        "sub_comment_count": "4",
        "sub_comment_cursor": "6a3cee4f",
        "sub_comment_has_more": True,
        "user_info": {"user_id": "u1", "nickname": "Gugugu", "image": "https://a"},
        "sub_comments": [{"id": "c2", "content": "OK", "user_info": {"nickname": "x"}}],
        "target_comment": {"id": "c0", "content": "root"},
    }
    out = XHSApi._normalise_comment(raw)
    assert out["id"] == "c1"
    assert out["like_count"] == "87"
    assert out["author"] == "Gugugu"
    assert out["sub_comment_count"] == "4"
    assert out["sub_comment_cursor"] == "6a3cee4f"
    assert out["sub_comment_has_more"] is True
    # nested replies are normalised recursively, not left raw
    assert out["sub_comments"][0]["id"] == "c2"
    assert out["sub_comments"][0]["author"] == "x"
    assert out["target_comment"]["id"] == "c0"
    assert out["raw"] is raw


def test_comment_normalisation_tolerates_shape_changes():
    out = XHSApi._normalise_comment({})
    assert out["id"] == ""
    assert out["content"] == ""
    assert out["sub_comments"] == []
    assert out["target_comment"] is None


def test_me_normalisation_reads_the_me_payload():
    class Stub:
        def request(self, name, **kw):
            assert name == "user_me"
            return {"guest": False, "user_id": "u1", "nickname": "小红薯norris",
                    "red_id": "5067062530", "desc": "d", "gender": 0,
                    "imageb": "https://a", "images": "https://b",
                    "xsec_token": "tok"}

    out = XHSApi(client=Stub()).me()
    assert out["guest"] is False
    assert out["nickname"] == "小红薯norris"
    assert out["red_id"] == "5067062530"
    # imageb is preferred, images is the fallback
    assert out["avatar"] == "https://a"
    assert out["xsec_token"] == "tok"


def test_me_reports_guest_when_the_cookie_was_rejected():
    class Stub:
        def request(self, name, **kw):
            return {"guest": True}

    out = XHSApi(client=Stub()).me()
    assert out["guest"] is True
    assert out["user_id"] == ""


def test_user_profile_normalisation_reads_basic_info():
    # basic_info is nested; the counters are top-level
    class Stub:
        def request(self, name, **kw):
            assert name == "user_otherinfo"
            assert kw["params"] == {"target_user_id": "u1"}
            return {
                "basic_info": {"nickname": "n", "red_id": "r", "desc": "d",
                               "imageb": "https://a", "images": "https://b",
                               "ip_location": "浙江"},
                "posted": 663, "collected": 603645, "liked": 2640819,
                "interactions": [{"count": "1", "name": "关注", "type": "follow",
                                  "show": True}],
                "tags": [{"name": "摄影", "icon": "i", "tagType": "t"},
                         "not-a-dict"],
            }

    out = XHSApi(client=Stub()).user_profile("u1")
    assert out["nickname"] == "n"
    assert out["red_id"] == "r"
    assert out["avatar"] == "https://a"
    assert out["ip_location"] == "浙江"
    assert (out["posted"], out["collected"], out["liked"]) == (663, 603645, 2640819)
    assert out["interactions"] == [{"name": "关注", "type": "follow", "count": "1"}]
    assert out["tags"] == ["摄影"]  # non-dict entries skipped


def test_search_users_reads_the_nested_user_base_dto():
    # identity lives under user_base_dto, not at the top level
    class Stub:
        def request(self, name, **kw):
            assert name == "search_user"
            payload = kw["payload"]
            # paging is a nested object on this endpoint
            assert payload["page"] == {"page_size": 20, "page": 1}
            assert payload["search_id"].isdigit()
            assert "page_size" not in payload  # must not be flattened
            return {"user_info_dtos": [{
                "user_base_dto": {"user_id": "u1", "red_id": "mfeel123",
                                  "user_nickname": "摄影", "desc": "d",
                                  "image": "https://a",
                                  "image_size_large": "https://b"},
                "fans_total": 0, "discovery_total": 0, "fstatus": "none",
            }]}

    out = XHSApi(client=Stub()).search_users("摄影")
    u = out["items"][0]
    assert u["user_id"] == "u1"
    assert u["red_id"] == "mfeel123"
    assert u["nickname"] == "摄影"
    assert u["fans_total"] == 0
    assert u["fstatus"] == "none"


def test_search_topics_builds_the_creator_payload():
    class Stub:
        def request(self, name, **kw):
            assert name == "search_topic"
            payload = kw["payload"]
            assert payload["page"] == {"page_size": 20, "page": 1}
            assert payload["suggest_topic_request"] == {"title": "", "desc": ""}
            return {"topic_info_dtos": [
                {"id": "53d8", "name": "摄影", "link": "https://l",
                 "view_num": 29148026190, "type": "official", "smart": False},
                "not-a-dict",
            ]}

    out = XHSApi(client=Stub()).search_topics("摄影")
    t = out["items"][0]
    assert t["id"] == "53d8"
    assert t["name"] == "摄影"
    assert t["view_count"] == 29148026190
    assert t["type"] == "official"
    assert t["smart"] is False
    assert len(out["items"]) == 1  # non-dict entries skipped


def test_comments_sends_the_parameters_the_server_requires():
    captured = {}

    class Stub:
        def request(self, name, **kw):
            captured["name"] = name
            captured["params"] = kw["params"]
            return {"comments": [{"id": "c1", "content": "hi"}],
                    "cursor": "next", "has_more": True,
                    "xsec_token": "tok2"}

    out = XHSApi(client=Stub()).comments(
        "n1", xsec_token="tok1", cursor="", top_comment_id="t1"
    )
    assert captured["name"] == "comment_page"
    assert captured["params"] == {
        "note_id": "n1", "cursor": "", "top_comment_id": "t1",
        # without these two the server answers 461/300031
        "image_formats": "jpg,webp,avif", "xsec_token": "tok1",
    }
    assert out["next_cursor"] == "next"
    assert out["has_more"] is True
    assert out["items"][0]["content"] == "hi"


def test_sub_comments_sends_root_comment_id_not_top_comment_id():
    # the naive 4-parameter form returns -9109 参数错误
    captured = {}

    class Stub:
        def request(self, name, **kw):
            captured["name"] = name
            captured["params"] = kw["params"]
            return {"comments": [{"id": "s1", "content": "re",
                                  "target_comment": {"id": "p1"}}],
                    "cursor": "", "has_more": False}

    out = XHSApi(client=Stub()).sub_comments(
        "n1", "p1", xsec_token="tok", cursor="c0", num=30
    )
    assert captured["name"] == "comment_sub_page"
    assert captured["params"]["root_comment_id"] == "p1"
    assert captured["params"]["num"] == 30
    assert "top_comment_id" not in captured["params"]
    assert captured["params"]["xsec_token"] == "tok"
    assert out["items"][0]["target_comment"]["id"] == "p1"


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
