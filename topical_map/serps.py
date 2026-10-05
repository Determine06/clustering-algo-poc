"""Collect Google organic SERPs from DataForSEO, one keyword per request."""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

from topical_map.storage import (
    KEYWORDS_PATH,
    PROJECT_ROOT,
    SERPS_PATH,
    load_json,
    save_json_atomic,
)


API_URL = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"
REQUEST_TIMEOUT_SECONDS = 120
SUCCESS_STATUS_CODE = 20000
FATAL_HTTP_STATUS_CODES = {401, 402, 403}
FATAL_API_STATUS_CODES = {
    40100,  # Invalid API credentials.
    40104,  # Account verification required.
    40200,  # Payment required.
    40201,  # Account access paused.
    40203,  # Account cost limit exceeded.
    40204,  # Subscription access required.
    40207,  # Account IP whitelist denied access.
    40208,  # Account blocked.
    40210,  # Insufficient funds.
}


class CollectionError(Exception):
    """A single keyword could not be collected."""


class FatalCollectionError(CollectionError):
    """The run cannot safely continue."""


@dataclass
class Summary:
    saved: int = 0
    skipped: int = 0
    failed: int = 0


def _load_array(path: Path, label: str, *, missing_ok: bool) -> list[Any]:
    if not path.exists() and not missing_ok:
        raise FatalCollectionError(f"{label} file not found: {path}")
    try:
        value = load_json(path, [])
    except (json.JSONDecodeError, OSError) as error:
        raise FatalCollectionError(f"Could not read {label} JSON at {path}: {error}") from error
    if not isinstance(value, list):
        raise FatalCollectionError(f"{label} JSON must contain an array: {path}")
    return value


def _load_keywords(path: Path) -> list[str]:
    records = _load_array(path, "Keyword", missing_ok=False)
    keywords: list[str] = []
    for index, record in enumerate(records):
        keyword = record.get("keyword") if isinstance(record, dict) else None
        if not isinstance(keyword, str) or not keyword.strip():
            raise FatalCollectionError(f"Invalid keyword record at index {index}: {path}")
        keywords.append(keyword)
    return keywords


def _load_saved_records(path: Path) -> list[dict[str, Any]]:
    records = _load_array(path, "Existing SERP", missing_ok=True)
    for index, record in enumerate(records):
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("keyword"), str)
            or not isinstance(record.get("results"), list)
        ):
            raise FatalCollectionError(f"Invalid existing SERP record at index {index}: {path}")
    return records


def _is_fatal_api_status(status_code: Any) -> bool:
    try:
        return int(status_code) in FATAL_API_STATUS_CODES
    except (TypeError, ValueError):
        return False


def _check_api_status(payload: dict[str, Any], scope: str) -> None:
    status_code = payload.get("status_code")
    status_message = str(payload.get("status_message") or "Unknown API error")
    if status_code == SUCCESS_STATUS_CODE:
        return
    error_type = (
        FatalCollectionError
        if _is_fatal_api_status(status_code)
        else CollectionError
    )
    raise error_type(f"{scope} status {status_code}: {status_message}")


def _parse_response(response: Any) -> list[dict[str, Any]]:
    if response.status_code != 200:
        status_message = str(getattr(response, "reason", "HTTP error"))
        try:
            body = response.json()
            if isinstance(body, dict):
                status_message = str(body.get("status_message") or status_message)
        except (ValueError, json.JSONDecodeError):
            pass
        error_type = (
            FatalCollectionError
            if response.status_code in FATAL_HTTP_STATUS_CODES
            else CollectionError
        )
        raise error_type(f"HTTP {response.status_code}: {status_message}")

    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError) as error:
        raise CollectionError("DataForSEO returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise CollectionError("DataForSEO response must be a JSON object")

    _check_api_status(payload, "Top-level")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks or not isinstance(tasks[0], dict):
        raise CollectionError("DataForSEO response is missing tasks[0]")
    task = tasks[0]
    _check_api_status(task, "Task")

    result = task.get("result")
    if not isinstance(result, list) or not result or not isinstance(result[0], dict):
        raise CollectionError("DataForSEO response is missing tasks[0].result[0]")
    items = result[0].get("items")
    if not isinstance(items, list):
        raise CollectionError("DataForSEO response is missing organic result items")

    organic_items: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "organic":
            continue
        try:
            rank = int(item.get("rank_group"))
        except (TypeError, ValueError):
            continue
        if rank < 1 or not isinstance(item.get("url"), str) or not item["url"]:
            continue
        organic_items.append((rank, item))

    organic_items.sort(key=lambda pair: pair[0])
    results = [
        {
            "rank": rank,
            "url": item["url"],
            "title": str(item.get("title") or ""),
        }
        for rank, item in organic_items[:10]
    ]
    if not results:
        raise CollectionError("DataForSEO returned zero organic results")
    return results


def _fetch_keyword(
    keyword: str,
    login: str,
    password: str,
    post: Callable[..., Any],
) -> list[dict[str, Any]]:
    payload = [
        {
            "keyword": keyword,
            "location_code": 2840,
            "language_code": "en",
            "device": "desktop",
            "os": "windows",
            "depth": 10,
        }
    ]
    try:
        response = post(
            API_URL,
            auth=HTTPBasicAuth(login, password),
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise CollectionError(f"Request failed: {error}") from error
    return _parse_response(response)


def _print_summary(summary: Summary) -> None:
    print(
        f"Summary: saved={summary.saved} "
        f"skipped={summary.skipped} failed={summary.failed}"
    )


def _save_completed(
    future: Future[list[dict[str, Any]]],
    keyword: str,
    saved_records: list[dict[str, Any]],
    serps_path: Path,
    summary: Summary,
) -> FatalCollectionError | None:
    """Process one completed worker future on the main thread."""
    try:
        results = future.result()
    except FatalCollectionError as error:
        summary.failed += 1
        print(f"Fatal error for {keyword}: {error}", file=sys.stderr)
        return error
    except CollectionError as error:
        summary.failed += 1
        print(f"Failed {keyword}: {error}", file=sys.stderr)
        return None

    if len(results) < 10:
        print(f"Warning: {keyword} returned only {len(results)} organic results.")
    saved_records.append(
        {
            "keyword": keyword,
            "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "results": results,
        }
    )
    try:
        save_json_atomic(serps_path, saved_records)
    except OSError as error:
        saved_records.pop()
        summary.failed += 1
        raise FatalCollectionError(f"Could not atomically save {serps_path}: {error}") from error
    summary.saved += 1
    print(f"Saved {keyword} ({len(results)} organic results).")
    return None


def update_serps(
    *,
    login: str,
    password: str,
    limit: int | None = None,
    workers: int = 10,
    keywords_path: Path = KEYWORDS_PATH,
    serps_path: Path = SERPS_PATH,
    post: Callable[..., Any] = requests.post,
) -> Summary:
    if workers < 1:
        raise FatalCollectionError("workers must be at least 1")
    keywords = _load_keywords(keywords_path)
    saved_records = _load_saved_records(serps_path)
    saved_keywords = {record["keyword"] for record in saved_records}
    summary = Summary(skipped=sum(keyword in saved_keywords for keyword in keywords))
    missing_keywords = [keyword for keyword in keywords if keyword not in saved_keywords]
    if limit is not None:
        missing_keywords = missing_keywords[:limit]

    print(
        f"Loaded {len(keywords)} keywords; {summary.skipped} already saved; "
        f"attempting {len(missing_keywords)} with {workers} worker(s)."
    )
    keyword_iterator = iter(missing_keywords)
    pending: dict[Future[list[dict[str, Any]]], str] = {}
    fatal_error: FatalCollectionError | None = None
    interrupted = False
    executor = ThreadPoolExecutor(max_workers=workers)

    def submit_until_full() -> None:
        while len(pending) < workers:
            try:
                keyword = next(keyword_iterator)
            except StopIteration:
                return
            print(f"Submitting: {keyword}")
            future = executor.submit(_fetch_keyword, keyword, login, password, post)
            pending[future] = keyword

    submit_until_full()
    try:
        while pending:
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                keyword = pending.pop(future)
                error = _save_completed(future, keyword, saved_records, serps_path, summary)
                if fatal_error is None and error is not None:
                    fatal_error = error
            if fatal_error is None:
                submit_until_full()
    except KeyboardInterrupt:
        interrupted = True
        print("Interrupted; waiting for in-flight requests to finish...", file=sys.stderr)
    finally:
        executor.shutdown(wait=True, cancel_futures=False)

    # On Ctrl+C, shutdown waits for the submitted requests; save their results now.
    if interrupted:
        for future, keyword in list(pending.items()):
            error = _save_completed(future, keyword, saved_records, serps_path, summary)
            if fatal_error is None and error is not None:
                fatal_error = error

    _print_summary(summary)
    if interrupted:
        raise KeyboardInterrupt
    if fatal_error is not None:
        raise fatal_error
    return summary


def _non_negative_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    update_parser = subparsers.add_parser("update", help="Fetch missing SERPs")
    update_parser.add_argument(
        "--limit",
        type=_non_negative_integer,
        help="Maximum number of missing keywords to attempt",
    )
    update_parser.add_argument(
        "--workers",
        type=_positive_integer,
        default=10,
        help="Concurrent requests (default: 10; use 1 for sequential processing)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    login = os.getenv("DATAFORSEO_LOGIN")
    password = os.getenv("DATAFORSEO_PASSWORD")
    if not login or not password:
        print(
            "Missing DATAFORSEO_LOGIN or DATAFORSEO_PASSWORD. "
            "Add both to the repository-root .env file.",
            file=sys.stderr,
        )
        return 1

    try:
        update_serps(
            login=login,
            password=password,
            limit=args.limit,
            workers=args.workers,
        )
    except FatalCollectionError as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Stopped after saving completed in-flight requests.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
