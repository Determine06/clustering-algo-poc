"""Small URL-set fixtures for anchor selection and one-pass reassignment."""

import unittest

from topical_map.clustering import build_anchor_groups
from topical_map.overlap import build_overlap_analysis, graph_edges


def analyze(rows):
    return build_overlap_analysis(
        [{"keyword": keyword, "search_volume": volume} for keyword, volume, _ in rows],
        [{"keyword": keyword, "results": [
            {"rank": rank, "url": f"https://example.com/{url}", "title": url}
            for rank, url in enumerate(urls, 1)
        ]} for keyword, _, urls in rows],
    )


class AnchorGroupTests(unittest.TestCase):
    def test_chain_cannot_qualify_without_direct_anchor_overlap(self):
        analysis = analyze([
            ("A", 100, ["1", "2"]), ("B", 90, ["2", "3"]),
            ("C", 80, ["3", "4"]),
        ])
        groups = build_anchor_groups(analysis, 1)
        self.assertEqual(groups.anchors, ("A", "C"))
        self.assertEqual(groups.members, {"A": ("A", "B"), "C": ("C",)})
        self.assertTrue(groups.assignments["B"].ambiguous)
        # Cross-group B-C is still present at every display setting.
        for count in (1, 5, 10):
            self.assertIn(("B", "C"), [(p.keyword_a, p.keyword_b) for p in graph_edges(analysis, count)])

    def test_reassignment_chooses_best_anchor_and_anchors_stay_fixed(self):
        analysis = analyze([
            ("A", 100, ["1", "2", "3", "4", "5", "6"]),
            ("B", 90, ["7", "8", "9"]),
            ("member", 10, ["1", "2", "7", "8"]),
        ])
        groups = build_anchor_groups(analysis, 2)
        self.assertEqual(groups.anchors, ("A", "B"))
        self.assertEqual(groups.members["A"], ("A",))
        self.assertEqual(groups.members["B"], ("B", "member"))
        assignment = groups.assignments["member"]
        self.assertEqual(assignment.best.anchor, "B")
        self.assertAlmostEqual(assignment.best.jaccard, 2 / 5)
        self.assertEqual(assignment.second.anchor, "A")
        self.assertAlmostEqual(assignment.second.jaccard, 2 / 8)
        self.assertFalse(assignment.ambiguous)
        for anchor in groups.anchors:
            self.assertEqual(groups.assignments[anchor].best.anchor, anchor)
            self.assertIsNone(groups.assignments[anchor].second)

    def test_score_ties_use_anchor_volume_then_alphabetical_order(self):
        for volume_a, volume_b, expected in ((10, 20, "Beta"), (10, 10, "Alpha"), (0, None, "Alpha"), (None, None, "Alpha")):
            rows = [("Beta", volume_b, ["b", "b2"]),
                    ("Alpha", volume_a, ["a", "a2"]),
                    ("z member", None, ["a", "b"])]
            with self.subTest(volumes=(volume_a, volume_b)):
                groups = build_anchor_groups(analyze(rows), 1)
                self.assertEqual(groups.assignments["z member"].best.anchor, expected)
                self.assertTrue(groups.assignments["z member"].ambiguous)
                self.assertEqual(groups, build_anchor_groups(analyze(list(reversed(rows))), 1))

    def test_anchor_selection_puts_zero_volume_before_missing_and_breaks_ties(self):
        groups = build_anchor_groups(analyze([
            ("missing b", None, ["a"]), ("Zero", 0, ["a"]),
            ("missing a", None, ["b"]), ("beta", 100, ["c"]),
            ("Alpha", 100, ["c"]),
        ]), 1)
        self.assertEqual(groups.anchors, ("Alpha", "Zero", "missing a"))
        self.assertEqual(groups.members["Zero"], ("Zero", "missing b"))

    def test_ambiguity_includes_exact_five_percentage_points(self):
        groups = build_anchor_groups(analyze([
            ("A", 100, ["a", "d"]), ("B", 90, ["b", "e", "f"]),
            ("member", 10, ["a", "b", "c"]),
            ("only A", 1, ["d"]),
        ]), 1)
        assignment = groups.assignments["member"]
        self.assertAlmostEqual(assignment.best.jaccard, 0.25)
        self.assertAlmostEqual(assignment.second.jaccard, 0.20)
        self.assertTrue(assignment.ambiguous)
        self.assertIsNone(groups.assignments["only A"].second)
        self.assertFalse(groups.assignments["only A"].ambiguous)

    def test_singletons_missing_evidence_and_threshold(self):
        analysis = analyze([("A", 10, ["1"]), ("B", 5, ["1"]), ("empty", 100, [])])
        self.assertEqual(analysis.excluded_keywords, ("empty",))
        groups = build_anchor_groups(analysis, 2)
        self.assertEqual(groups.members, {"A": ("A",), "B": ("B",)})
        for stats in groups.statistics.values():
            self.assertIsNone(stats.average_jaccard)
            self.assertIsNone(stats.zero_overlap_fraction)
        self.assertEqual(len(build_anchor_groups(analysis, 1).anchors), 1)
        self.assertEqual(build_anchor_groups(analyze([])).anchors, ())

    def test_group_statistics_include_anchor_and_zero_overlap_member_pairs(self):
        groups = build_anchor_groups(analyze([
            ("A", 100, ["1", "2"]), ("B", 10, ["1", "3"]),
            ("C", 5, ["2", "4"]),
        ]), 1)
        self.assertEqual(groups.members["A"], ("A", "B", "C"))
        stats = groups.statistics["A"]
        self.assertAlmostEqual(stats.average_jaccard, 2 / 9)
        self.assertAlmostEqual(stats.zero_overlap_fraction, 1 / 3)


if __name__ == "__main__":
    unittest.main()
