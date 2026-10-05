"""Pure calculations for exploring shared organic SERP URLs."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_PARAMETERS = {"gclid", "fbclid", "msclkid", "srsltid"}


def _keyword_sort_key(keyword: str) -> tuple[str, str]:
    return keyword.casefold(), keyword


def _pair_key(keyword_a: str, keyword_b: str) -> tuple[str, str]:
    return tuple(sorted((keyword_a, keyword_b), key=_keyword_sort_key))


@dataclass(frozen=True)
class RankingResult:
    rank: int
    url: str
    title: str
    normalized_url: str


@dataclass(frozen=True)
class KeywordEvidence:
    keyword: str
    search_volume: int | float | None
    results: tuple[RankingResult, ...]
    urls: frozenset[str]


@dataclass(frozen=True)
class PairOverlap:
    keyword_a: str
    keyword_b: str
    size_a: int
    size_b: int
    shared_count: int
    jaccard: float
    shared_urls: tuple[str, ...]


@dataclass(frozen=True)
class OverlapAnalysis:
    evidence: dict[str, KeywordEvidence]
    pairs: dict[tuple[str, str], PairOverlap]
    excluded_keywords: tuple[str, ...]

    @property
    def keywords(self) -> tuple[str, ...]:
        return tuple(self.evidence)


def normalize_url(url: str) -> str | None:
    """Normalize a URL without collapsing meaningful URL distinctions."""
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parts = urlsplit(url.strip())
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return None
        hostname = parts.hostname.lower()
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        credentials = ""
        if "@" in parts.netloc:
            credentials = f"{parts.netloc.rsplit('@', 1)[0]}@"
        port = f":{parts.port}" if parts.port is not None else ""
        netloc = f"{credentials}{hostname}{port}"
    except ValueError:
        return None

    query_items = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in TRACKING_PARAMETERS
    ]
    return urlunsplit(
        (
            parts.scheme.lower(),
            netloc,
            parts.path,
            urlencode(query_items, doseq=True),
            "",
        )
    )


def _ranking_results(record: dict[str, Any] | None) -> tuple[RankingResult, ...]:
    raw_results = record.get("results") if isinstance(record, dict) else None
    if not isinstance(raw_results, list):
        return ()

    ranked: list[tuple[int, dict[str, Any]]] = []
    for result in raw_results:
        if not isinstance(result, dict):
            continue
        try:
            rank = int(result.get("rank"))
        except (TypeError, ValueError):
            continue
        if rank < 1 or not isinstance(result.get("url"), str):
            continue
        ranked.append((rank, result))

    usable: list[RankingResult] = []
    for rank, result in sorted(ranked, key=lambda item: item[0])[:10]:
        normalized = normalize_url(result["url"])
        if normalized is None:
            continue
        usable.append(
            RankingResult(
                rank=rank,
                url=result["url"],
                title=str(result.get("title") or ""),
                normalized_url=normalized,
            )
        )
    return tuple(usable)


def build_overlap_analysis(
    keyword_records: list[dict[str, Any]],
    serp_records: list[dict[str, Any]],
) -> OverlapAnalysis:
    """Build evidence and all unordered pair metrics from loaded JSON data."""
    serp_by_keyword = {
        record["keyword"]: record
        for record in serp_records
        if isinstance(record, dict) and isinstance(record.get("keyword"), str)
    }
    volumes: dict[str, int | float | None] = {}
    for record in keyword_records:
        if not isinstance(record, dict) or not isinstance(record.get("keyword"), str):
            continue
        volumes[record["keyword"]] = record.get("search_volume")

    evidence: dict[str, KeywordEvidence] = {}
    excluded: list[str] = []
    for keyword in sorted(volumes, key=_keyword_sort_key):
        results = _ranking_results(serp_by_keyword.get(keyword))
        urls = frozenset(result.normalized_url for result in results)
        if not urls:
            excluded.append(keyword)
            continue
        evidence[keyword] = KeywordEvidence(
            keyword=keyword,
            search_volume=volumes[keyword],
            results=results,
            urls=urls,
        )

    pairs: dict[tuple[str, str], PairOverlap] = {}
    for keyword_a, keyword_b in combinations(evidence, 2):
        urls_a = evidence[keyword_a].urls
        urls_b = evidence[keyword_b].urls
        shared_urls = tuple(sorted(urls_a & urls_b))
        union_size = len(urls_a | urls_b)
        pairs[(keyword_a, keyword_b)] = PairOverlap(
            keyword_a=keyword_a,
            keyword_b=keyword_b,
            size_a=len(urls_a),
            size_b=len(urls_b),
            shared_count=len(shared_urls),
            jaccard=len(shared_urls) / union_size,
            shared_urls=shared_urls,
        )
    return OverlapAnalysis(
        evidence=evidence,
        pairs=pairs,
        excluded_keywords=tuple(excluded),
    )


def get_pair(analysis: OverlapAnalysis, keyword_a: str, keyword_b: str) -> PairOverlap:
    """Return the stored unordered pair metric for two distinct keywords."""
    if keyword_a == keyword_b:
        raise ValueError("A pair requires two distinct keywords")
    key = _pair_key(keyword_a, keyword_b)
    return analysis.pairs[key]


def positive_neighbors(
    analysis: OverlapAnalysis,
    keyword: str,
) -> list[tuple[str, PairOverlap]]:
    """Return positive-overlap neighbors ordered by Jaccard and keyword."""
    neighbors: list[tuple[str, PairOverlap]] = []
    for pair in analysis.pairs.values():
        if pair.shared_count == 0:
            continue
        if pair.keyword_a == keyword:
            neighbors.append((pair.keyword_b, pair))
        elif pair.keyword_b == keyword:
            neighbors.append((pair.keyword_a, pair))
    return sorted(
        neighbors,
        key=lambda item: (-item[1].jaccard, *_keyword_sort_key(item[0])),
    )


def graph_edges(
    analysis: OverlapAnalysis,
    neighbors_per_keyword: int = 5,
    *,
    all_nonzero: bool = False,
) -> tuple[PairOverlap, ...]:
    """Select a readable union of strongest-neighbor edges."""
    if all_nonzero:
        selected = [pair for pair in analysis.pairs.values() if pair.shared_count > 0]
    else:
        selected_keys: set[tuple[str, str]] = set()
        for keyword in analysis.keywords:
            for neighbor, _ in positive_neighbors(analysis, keyword)[:neighbors_per_keyword]:
                selected_keys.add(_pair_key(keyword, neighbor))
        selected = [analysis.pairs[key] for key in selected_keys]
    return tuple(
        sorted(
            selected,
            key=lambda pair: (
                *_keyword_sort_key(pair.keyword_a),
                *_keyword_sort_key(pair.keyword_b),
            ),
        )
    )


def result_count_distribution(
    evidence: Iterable[KeywordEvidence],
) -> dict[int, int]:
    """Count keywords by the number of usable saved ranking results."""
    counts = {result_count: 0 for result_count in range(6, 11)}
    for item in evidence:
        result_count = len(item.results)
        if result_count in counts:
            counts[result_count] += 1
    return counts
