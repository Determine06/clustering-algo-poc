import copy
import unittest

from topical_map.clustering import build_anchor_groups
from topical_map.overlap import build_overlap_analysis, graph_edges
from topical_map.visuals import group_layout, group_view_edges, group_figure


class GroupVisualTests(unittest.TestCase):
    def setUp(self):
        rows = [("A", ["1", "2", "3"]), ("B", ["1", "2", "4"]),
                ("C", ["5", "6", "7"]), ("D", ["5", "6", "4"]),
                ("singleton", ["1", "8"])]
        self.analysis = build_overlap_analysis(
            [{"keyword": k, "search_volume": 100 - i} for i, (k, _) in enumerate(rows)],
            [{"keyword": k, "results": [{"rank": i, "url": f"https://example.com/{u}"}
              for i, u in enumerate(urls, 1)]} for k, urls in rows],
        )
        self.groups = build_anchor_groups(self.analysis, 2)

    def test_separate_areas_singleton_filter_and_required_spokes(self):
        before = copy.deepcopy(self.groups)
        positions, centers, columns = group_layout(self.groups)
        self.assertNotIn("singleton", positions)  # Has overlap edges, still a singleton.
        self.assertEqual(group_layout(self.groups), (positions, centers, columns))
        for anchor, center in centers.items():
            self.assertEqual(positions[anchor], center)
            for member in self.groups.members[anchor]:
                self.assertLessEqual(abs(positions[member][0] - center[0]), 1.2)
                self.assertLessEqual(abs(positions[member][1] - center[1]), 1.2)
        self.assertGreater(abs(centers['A'][0] - centers['C'][0]), 3.6)
        spokes = group_view_edges(self.analysis, self.groups, positions, (), False)
        self.assertEqual({(p.keyword_a, p.keyword_b) for p in spokes}, {("A", "B"), ("C", "D")})
        all_edges = graph_edges(self.analysis, all_nonzero=True)
        edges = group_view_edges(self.analysis, self.groups, positions, all_edges, True)
        self.assertIn(("B", "D"), [(p.keyword_a, p.keyword_b) for p in edges])
        self.assertEqual(len(group_layout(self.groups, False)[0]), 5)
        figure = group_figure(self.analysis, self.groups, positions, centers, columns, edges, None, "A")
        self.assertEqual(list(figure.data[-1].marker.opacity), [1, 1, 0.18, 0.18])
        self.assertEqual(len(figure.layout.annotations), 2)
        self.assertEqual(self.groups, before)


if __name__ == "__main__":
    unittest.main()
