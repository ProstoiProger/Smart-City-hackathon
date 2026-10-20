import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import requests

from scripts.collect_reviews import (
    Fetcher,
    StopRun,
    build_targets,
    decode_js_string,
    extract_state,
    looks_like_access_check,
    parse_page,
)

BID = "70000001000000001"
URL = f"https://2gis.kz/astana/firm/{BID}/tab/reviews"
TARGET = {"branch_id": BID, "source_poi_ids": [f"dgis:{BID}"], "canonical_poi_ids": ["c1"]}


def js_quote(text):
    return text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")


def page_html(state):
    payload = js_quote(json.dumps(state, ensure_ascii=False))
    return f"<html><script>window.x=1;__REACT_QUERY_STATE__ = JSON.parse('{payload}');</script></html>"


def review(rid, branch=BID, **extra):
    item = {
        "id": rid,
        "text": "Есть розетки, тихо.\nКофе \"хороший\" — it's ok \\ ☕",
        "rating": 5,
        "date_created": "2026-10-03T14:56:48+07:00",
        "date_edited": None,
        "is_hidden": False,
        "is_rated": True,
        "object": {"id": branch, "type": "branch"},
        "official_answer": None,
        "provider": "2gis",
        "url": "",
        "user": {"name": "Private Person", "id": "u1", "photo_preview_urls": {"x": "y"}},
        "trust_factors": {"trust_info": {"confirmed_caption": "Отзыв подтверждён"}},
    }
    item.update(extra)
    return item


def state_with(items, branch=BID, total=None):
    return {
        "mutations": [],
        "queries": [
            {"queryKey": ["fetchEntityAlbums", {"objectId": branch}], "state": {"data": {"albums": []}}},
            {
                "queryKey": ["fetchEntityReviews", ["99999", "branch", None, "trust"]],
                "state": {"data": {"pages": [{"items": [review("other", "99999")], "total": 1}]}},
            },
            {
                "queryKey": ["fetchEntityReviews", [branch, "branch", None, None, "trust"]],
                "state": {
                    "data": {
                        "pages": [
                            {
                                "items": items,
                                "total": len(items) if total is None else total,
                                "hasMore": False,
                                "next_link": "https://public-api.reviews.2gis.com/x?key=SECRET",
                            }
                        ]
                    }
                },
            },
        ],
    }


class ReviewParsingTests(unittest.TestCase):
    def test_state_is_decoded_without_running_scripts(self):
        state = state_with([review("1")])
        self.assertEqual(extract_state(page_html(state)), state)

    def test_js_unicode_escapes_and_surrogate_pairs(self):
        self.assertEqual(decode_js_string(r"\u0410\x41\ud83d\ude00\u{1F600}"), "АA😀😀")

    def test_reviews_belong_to_requested_branch_only(self):
        items = [review("1"), review("2", branch="555")]
        status, reviews, summary = parse_page(page_html(state_with(items)), URL, TARGET, "t")
        self.assertEqual(status, "complete_first_page")
        self.assertEqual([r["review_id"] for r in reviews], ["1"])
        self.assertEqual(summary["foreign_items_dropped"], 1)
        self.assertEqual(reviews[0]["canonical_poi_ids"], ["c1"])
        self.assertIn("розетки", reviews[0]["text"])

    def test_no_author_data_or_access_parameters_are_saved(self):
        _, reviews, summary = parse_page(page_html(state_with([review("1")])), URL, TARGET, "t")
        dumped = json.dumps([reviews, summary], ensure_ascii=False)
        for leaked in ("Private Person", "photo_preview", "SECRET", "next_link", '"user"'):
            self.assertNotIn(leaked, dumped)

    def test_operator_answer_is_kept_apart_and_hidden_text_dropped(self):
        items = [
            review("1", official_answer={"text": "Спасибо!", "date_created": "d", "org_name": "X"}),
            review("2", is_hidden=True),
        ]
        _, reviews, summary = parse_page(page_html(state_with(items)), URL, TARGET, "t")
        self.assertEqual(reviews[0]["operator_answer"], {"text": "Спасибо!", "date_created": "d"})
        self.assertNotEqual(reviews[0]["text"], "Спасибо!")
        self.assertIsNone(reviews[1]["text"])
        self.assertTrue(reviews[1]["text_empty"])
        self.assertEqual(summary["hidden"], 1)

    def test_zero_reviews_versus_changed_page(self):
        status, _, _ = parse_page(page_html(state_with([], total=0)), URL, TARGET, "t")
        self.assertEqual(status, "no_public_reviews_as_reported")
        status, _, _ = parse_page(page_html(state_with([], total=12)), URL, TARGET, "t")
        self.assertEqual(status, "schema_changed")
        unrated = state_with([], total=1)
        unrated["queries"][2]["state"]["data"]["pages"][0]["totalForRequest"] = 0
        status, _, _ = parse_page(page_html(unrated), URL, TARGET, "t")
        self.assertEqual(status, "only_unrated_reviews_not_collected")
        status, _, _ = parse_page("<html>nothing</html>", URL, TARGET, "t")
        self.assertEqual(status, "schema_changed")
        missing = {"queries": [{"queryKey": ["fetchEntityAlbums", {}], "state": {"data": {}}}]}
        status, _, _ = parse_page(page_html(missing), URL, TARGET, "t")
        self.assertEqual(status, "schema_changed")

    def test_redirects_are_not_parsed_as_this_branch(self):
        html = page_html(state_with([review("1")]))
        status, reviews, _ = parse_page(html, "https://2gis.kz/museum?return_url=x", TARGET, "t")
        self.assertEqual((status, reviews), ("unsupported_browser_page", []))
        status, _, _ = parse_page(html, "https://2gis.kz/almaty/firm/123/tab/reviews", TARGET, "t")
        self.assertEqual(status, "redirected")

    def test_captcha_word_in_normal_page_is_not_a_block(self):
        self.assertFalse(looks_like_access_check(page_html(state_with([])) + "<script>captcha</script>"))
        self.assertTrue(looks_like_access_check("<html>Подтвердите, что вы не робот: captcha</html>"))


class StorageTests(unittest.TestCase):
    def test_unicode_line_separator_inside_text_does_not_split_rows(self):
        from scripts.collect_reviews import read_jsonl

        rows = [{"branch_id": BID, "text": "строка вторая\x85третья"}, {"branch_id": "2"}]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "r.jsonl"
            with open(path, "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            self.assertEqual(list(read_jsonl(path)), rows)


class TargetTests(unittest.TestCase):
    def test_branch_ids_come_from_identity_fields_and_map_to_canonical(self):
        rows = [
            {"poi_id": f"dgis:{BID}", "ratings_count": 3},
            {"poi_id": "osm:node:1", "external_ids": {"2gis": BID}, "raw_2gis_id": BID, "ratings_count": 9},
            {"poi_id": "osm:node:2", "address": "дом 70000001000000002", "external_ids": {"osm": "node/2"}},
        ]
        with tempfile.TemporaryDirectory() as d:
            src, al = Path(d) / "s.jsonl", Path(d) / "a.json"
            src.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
            al.write_text(json.dumps({f"dgis:{BID}": "canon", "osm:node:1": "canon"}), encoding="utf-8")
            targets = build_targets(src, al)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["source_poi_ids"], [f"dgis:{BID}", "osm:node:1"])
        self.assertEqual(targets[0]["canonical_poi_ids"], ["canon"])
        self.assertEqual(targets[0]["ratings_count"], 9)

    def test_firm_links_in_identity_field_are_resolved(self):
        from scripts.collect_reviews import branch_ids_of

        poi = {"poi_id": "visitastana:a", "external_ids": {
            "2gis": "https://2gis.kz/nur_sultan/search/x/firm/70000001063704202/71.41%2C51.07?m=1"}}
        self.assertEqual(branch_ids_of(poi), ["70000001063704202"])
        poi["external_ids"]["2gis"] = "https://evil.example/firm/70000001063704202"
        self.assertEqual(branch_ids_of(poi), [])


class FetcherTests(unittest.TestCase):
    def _response(self, status, headers=None):
        r = Mock(status_code=status, headers=headers or {})
        r.__enter__ = Mock(return_value=r)
        r.__exit__ = Mock(return_value=False)
        return r

    def test_forbidden_stops_the_run(self):
        f = Fetcher(max_requests=5)
        f.session.get = Mock(return_value=self._response(403))
        with self.assertRaises(StopRun):
            f.get(URL)

    def test_network_errors_do_not_leak_urls(self):
        f = Fetcher(max_requests=3)
        f._wait = Mock()
        f.session.get = Mock(side_effect=requests.ConnectionError("https://x/?key=SECRET"))
        html, status = f.get(URL)
        self.assertEqual((html, status), (None, "partial_network_error"))

    def test_local_request_cap(self):
        f = Fetcher(max_requests=0)
        self.assertEqual(f.get(URL), (None, "partial_local_limit"))


if __name__ == "__main__":
    unittest.main()
