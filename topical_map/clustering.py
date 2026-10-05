"""Deterministic anchor groups derived only from existing URL overlap."""

from dataclasses import dataclass
from itertools import combinations
from math import isclose

from topical_map.overlap import OverlapAnalysis, get_pair


@dataclass(frozen=True)
class AnchorMatch:
    anchor: str
    shared_count: int
    jaccard: float


@dataclass(frozen=True)
class Assignment:
    best: AnchorMatch
    second: AnchorMatch | None = None
    ambiguous: bool = False


@dataclass(frozen=True)
class GroupStatistics:
    average_jaccard: float | None
    zero_overlap_fraction: float | None


@dataclass(frozen=True)
class AnchorGroups:
    anchors: tuple[str, ...]
    members: dict[str, tuple[str, ...]]
    assignments: dict[str, Assignment]
    statistics: dict[str, GroupStatistics]


def build_anchor_groups(analysis: OverlapAnalysis, minimum_shared: int = 3) -> AnchorGroups:
    """Choose anchors once, then reassign non-anchors once against all anchors.

    Shared count controls qualification; Jaccard chooses among qualifying
    anchors. The ambiguity flag is an exploratory score-gap heuristic.
    """
    if not 1 <= minimum_shared <= 10:
        raise ValueError("minimum_shared must be between 1 and 10")

    def priority(keyword: str) -> tuple:
        volume = analysis.evidence[keyword].search_volume
        return (volume is None, -volume if volume is not None else 0,
                keyword.casefold(), keyword)

    ordered = sorted(analysis.keywords, key=priority)
    unassigned = set(ordered)
    anchors = []
    for keyword in ordered:
        if keyword not in unassigned:
            continue
        anchors.append(keyword)
        unassigned.remove(keyword)
        provisional_members = {
            other for other in unassigned
            if get_pair(analysis, keyword, other).shared_count >= minimum_shared
        }
        unassigned.difference_update(provisional_members)

    members = {anchor: [anchor] for anchor in anchors}
    assignments = {
        anchor: Assignment(AnchorMatch(anchor, len(analysis.evidence[anchor].urls), 1.0))
        for anchor in anchors
    }
    for keyword in ordered:
        if keyword in assignments:
            continue
        matches = []
        for anchor in anchors:
            pair = get_pair(analysis, keyword, anchor)
            if pair.shared_count >= minimum_shared:
                matches.append(AnchorMatch(anchor, pair.shared_count, pair.jaccard))
        matches.sort(key=lambda match: (-match.jaccard, *priority(match.anchor)))
        # Every non-anchor qualified for a provisional anchor, which stays fixed.
        best = matches[0]
        second = matches[1] if len(matches) > 1 else None
        gap = best.jaccard - second.jaccard if second else None
        ambiguous = gap is not None and (gap <= 0.05 or isclose(gap, 0.05, abs_tol=1e-12))
        assignments[keyword] = Assignment(best, second, ambiguous)
        members[best.anchor].append(keyword)

    statistics = {}
    for anchor, group in members.items():
        pairs = [get_pair(analysis, a, b) for a, b in combinations(group, 2)]
        statistics[anchor] = GroupStatistics(
            average_jaccard=sum(pair.jaccard for pair in pairs) / len(pairs) if pairs else None,
            zero_overlap_fraction=sum(pair.shared_count == 0 for pair in pairs) / len(pairs) if pairs else None,
        )
    return AnchorGroups(
        anchors=tuple(anchors),
        members={anchor: tuple(group) for anchor, group in members.items()},
        assignments=assignments,
        statistics=statistics,
    )
