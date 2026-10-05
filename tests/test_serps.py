from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from topical_map.serps import FatalCollectionError, _parse_response, update_serps


class MockResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.reason = "Mock response"

    def json(self) -> dict[str, Any]:
        return self.payload


def successful_payload(keyword: str = "new keyword") -> dict[str, Any]:
    return {
        "status_code": 20000,
        "status_message": "Ok.",
        "tasks": [
            {
                "status_code": 20000,
                "status_message": "Ok.",
                "result": [
                    {
                        "items": [
                            {
                                "type": "paid",
                                "rank_group": 1,
                                "url": "https://ads.example.com",
                                "title": "Ad",
                            },
                            {
                                "type": "organic",
                                "rank_group": 2,
                                "url": f"https://example.com/{keyword}/two",
                                "title": "Second",
                            },
                            {
                                "type": "organic",
                                "rank_group": 1,
                                "url": f"https://example.com/{keyword}/one",
                                "title": "First",
                            },
                        ]
                    }
                ],
            }
        ],
    }


class SerpCollectorTests(unittest.TestCase):
    def test_parses_and_sorts_only_organic_results(self) -> None:
        results = _parse_response(MockResponse(successful_payload()))
        self.assertEqual([result["rank"] for result in results], [1, 2])
        self.assertTrue(results[0]["url"].endswith("/one"))

    def test_skips_saved_keywords_and_saves_each_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keywords_path = root / "keyword_list.json"
            serps_path = root / "serp_data.json"
            keywords_path.write_text(
                json.dumps(
                    [
                        {"keyword": "saved keyword", "search_volume": 10},
                        {"keyword": "new keyword", "search_volume": None},
                    ]
                ),
                encoding="utf-8",
            )
            serps_path.write_text(
                json.dumps(
                    [
                        {
                            "keyword": "saved keyword",
                            "fetched_at": "2026-01-01T00:00:00Z",
                            "results": [
                                {
                                    "rank": 1,
                                    "url": "https://saved.example",
                                    "title": "Saved",
                                }
                            ],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            calls: list[dict[str, Any]] = []

            def post(*args: Any, **kwargs: Any) -> MockResponse:
                calls.append(kwargs)
                return MockResponse(successful_payload())

            summary = update_serps(
                login="login",
                password="password",
                keywords_path=keywords_path,
                serps_path=serps_path,
                post=post,
            )

            self.assertEqual((summary.saved, summary.skipped, summary.failed), (1, 1, 0))
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["timeout"], 120)
            saved = json.loads(serps_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [record["keyword"] for record in saved],
                ["saved keyword", "new keyword"],
            )

    def test_failed_result_is_not_saved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keywords_path = root / "keyword_list.json"
            serps_path = root / "serp_data.json"
            keywords_path.write_text(
                json.dumps([{"keyword": "no results", "search_volume": 1}]),
                encoding="utf-8",
            )
            payload = successful_payload()
            payload["tasks"][0]["result"][0]["items"] = []

            summary = update_serps(
                login="login",
                password="password",
                keywords_path=keywords_path,
                serps_path=serps_path,
                post=lambda *args, **kwargs: MockResponse(payload),
            )

            self.assertEqual((summary.saved, summary.failed), (0, 1))
            self.assertFalse(serps_path.exists())

    def test_authentication_error_stops_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keywords_path = root / "keyword_list.json"
            serps_path = root / "serp_data.json"
            keywords_path.write_text(
                json.dumps(
                    [
                        {"keyword": "first", "search_volume": 1},
                        {"keyword": "second", "search_volume": 1},
                    ]
                ),
                encoding="utf-8",
            )
            calls = 0

            def post(*args: Any, **kwargs: Any) -> MockResponse:
                nonlocal calls
                calls += 1
                return MockResponse(
                    {"status_code": 40100, "status_message": "Authentication failed"}
                )

            with self.assertRaises(FatalCollectionError):
                update_serps(
                    login="login",
                    password="password",
                    workers=1,
                    keywords_path=keywords_path,
                    serps_path=serps_path,
                    post=post,
                )
            self.assertEqual(calls, 1)
            self.assertFalse(serps_path.exists())

    def test_fatal_error_drains_and_saves_in_flight_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keywords_path = root / "keyword_list.json"
            serps_path = root / "serp_data.json"
            keywords_path.write_text(
                json.dumps(
                    [
                        {"keyword": "fatal", "search_volume": 1},
                        {"keyword": "in flight", "search_volume": 1},
                        {"keyword": "not submitted", "search_volume": 1},
                    ]
                ),
                encoding="utf-8",
            )
            barrier = threading.Barrier(2)
            calls: list[str] = []

            def post(*args: Any, **kwargs: Any) -> MockResponse:
                keyword = kwargs["json"][0]["keyword"]
                calls.append(keyword)
                barrier.wait(timeout=1)
                if keyword == "fatal":
                    return MockResponse(
                        {"status_code": 40100, "status_message": "Authentication failed"}
                    )
                time.sleep(0.05)
                return MockResponse(successful_payload(keyword))

            with self.assertRaises(FatalCollectionError):
                update_serps(
                    login="login",
                    password="password",
                    workers=2,
                    keywords_path=keywords_path,
                    serps_path=serps_path,
                    post=post,
                )

            self.assertCountEqual(calls, ["fatal", "in flight"])
            saved = json.loads(serps_path.read_text(encoding="utf-8"))
            self.assertEqual([record["keyword"] for record in saved], ["in flight"])

    def test_internal_se_error_does_not_stop_other_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keywords_path = root / "keyword_list.json"
            serps_path = root / "serp_data.json"
            keywords_path.write_text(
                json.dumps(
                    [
                        {"keyword": "temporary error", "search_volume": 1},
                        {"keyword": "success one", "search_volume": 1},
                        {"keyword": "success two", "search_volume": 1},
                    ]
                ),
                encoding="utf-8",
            )
            calls: list[str] = []

            def post(*args: Any, **kwargs: Any) -> MockResponse:
                keyword = kwargs["json"][0]["keyword"]
                calls.append(keyword)
                payload = successful_payload(keyword)
                if keyword == "temporary error":
                    payload["tasks"][0]["status_code"] = 40101
                    payload["tasks"][0]["status_message"] = "Internal SE Server Error"
                return MockResponse(payload)

            summary = update_serps(
                login="login",
                password="password",
                workers=2,
                keywords_path=keywords_path,
                serps_path=serps_path,
                post=post,
            )

            self.assertEqual((summary.saved, summary.failed), (2, 1))
            self.assertCountEqual(calls, ["temporary error", "success one", "success two"])
            saved = json.loads(serps_path.read_text(encoding="utf-8"))
            self.assertCountEqual(
                [record["keyword"] for record in saved],
                ["success one", "success two"],
            )

    def test_requests_run_concurrently_with_bounded_workers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keywords_path = root / "keyword_list.json"
            serps_path = root / "serp_data.json"
            keywords_path.write_text(
                json.dumps(
                    [
                        {"keyword": f"keyword {index}", "search_volume": 1}
                        for index in range(6)
                    ]
                ),
                encoding="utf-8",
            )
            barrier = threading.Barrier(3)
            lock = threading.Lock()
            active = 0
            max_active = 0

            def post(*args: Any, **kwargs: Any) -> MockResponse:
                nonlocal active, max_active
                keyword = kwargs["json"][0]["keyword"]
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                if keyword in {"keyword 0", "keyword 1", "keyword 2"}:
                    barrier.wait(timeout=1)
                time.sleep(0.01)
                with lock:
                    active -= 1
                return MockResponse(successful_payload(keyword))

            summary = update_serps(
                login="login",
                password="password",
                workers=3,
                keywords_path=keywords_path,
                serps_path=serps_path,
                post=post,
            )

            self.assertEqual(summary.saved, 6)
            self.assertEqual(max_active, 3)
            self.assertEqual(len(json.loads(serps_path.read_text(encoding="utf-8"))), 6)

    def test_interrupt_drains_and_saves_in_flight_successes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keywords_path = root / "keyword_list.json"
            serps_path = root / "serp_data.json"
            keywords_path.write_text(
                json.dumps(
                    [
                        {"keyword": "one", "search_volume": 1},
                        {"keyword": "two", "search_volume": 1},
                    ]
                ),
                encoding="utf-8",
            )

            def post(*args: Any, **kwargs: Any) -> MockResponse:
                keyword = kwargs["json"][0]["keyword"]
                return MockResponse(successful_payload(keyword))

            with patch("topical_map.serps.wait", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    update_serps(
                        login="login",
                        password="password",
                        workers=2,
                        keywords_path=keywords_path,
                        serps_path=serps_path,
                        post=post,
                    )

            saved = json.loads(serps_path.read_text(encoding="utf-8"))
            self.assertCountEqual(
                [record["keyword"] for record in saved],
                ["one", "two"],
            )

    def test_task_balance_error_is_fatal(self) -> None:
        payload = successful_payload()
        payload["tasks"][0]["status_code"] = 40201
        payload["tasks"][0]["status_message"] = "Insufficient balance"
        with self.assertRaises(FatalCollectionError):
            _parse_response(MockResponse(payload))

    def test_http_unauthorized_is_fatal(self) -> None:
        with self.assertRaises(FatalCollectionError):
            _parse_response(MockResponse({}, status_code=401))

    def test_limit_caps_missing_keyword_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keywords_path = root / "keyword_list.json"
            serps_path = root / "serp_data.json"
            keywords_path.write_text(
                json.dumps(
                    [
                        {"keyword": "one", "search_volume": 1},
                        {"keyword": "two", "search_volume": 1},
                        {"keyword": "three", "search_volume": 1},
                    ]
                ),
                encoding="utf-8",
            )
            calls = 0

            def post(*args: Any, **kwargs: Any) -> MockResponse:
                nonlocal calls
                calls += 1
                return MockResponse(successful_payload())

            summary = update_serps(
                login="login",
                password="password",
                limit=2,
                keywords_path=keywords_path,
                serps_path=serps_path,
                post=post,
            )

            self.assertEqual(summary.saved, 2)
            self.assertEqual(calls, 2)
            self.assertEqual(len(json.loads(serps_path.read_text(encoding="utf-8"))), 2)

    def test_invalid_existing_json_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keywords_path = root / "keyword_list.json"
            serps_path = root / "serp_data.json"
            keywords_path.write_text(
                json.dumps([{"keyword": "keyword", "search_volume": 1}]),
                encoding="utf-8",
            )
            serps_path.write_text("not valid json", encoding="utf-8")

            with self.assertRaises(FatalCollectionError):
                update_serps(
                    login="login",
                    password="password",
                    keywords_path=keywords_path,
                    serps_path=serps_path,
                    post=lambda *args, **kwargs: self.fail("API should not be called"),
                )
            self.assertEqual(serps_path.read_text(encoding="utf-8"), "not valid json")


if __name__ == "__main__":
    unittest.main()
