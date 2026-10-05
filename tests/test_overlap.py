from __future__ import annotations

import unittest

from topical_map.overlap import build_overlap_analysis, get_pair, normalize_url


def result(rank: int, url: str, title: str = "Title") -> dict[str, object]:
    return {"rank": rank, "url": url, "title": title}


class OverlapTests(unittest.TestCase):
    def test_normalization_removes_tracking_and_preserves_meaningful_parts(self) -> None:
        normalized = normalize_url(
            "HTTPS://WWW.Example.COM/Path/?utm_source=test&v=AbC&gclid=1"
            "&fbclid=2&msclkid=3&srsltid=4#section"
        )
        self.assertEqual(normalized, "https://www.example.com/Path/?v=AbC")
        self.assertEqual(
            normalize_url("http://example.com/Path"),
            "http://example.com/Path",
        )
        self.assertEqual(
            normalize_url("https://example.com/Path/"),
            "https://example.com/Path/",
        )
        self.assertNotEqual(
            normalize_url("https://example.com/Path"),
            normalize_url("https://example.com/path"),
        )
        self.assertNotEqual(
            normalize_url("https://www.example.com/Path"),
            normalize_url("https://example.com/Path"),
        )

    def test_identical_disjoint_partial_and_unequal_sets(self) -> None:
        keywords = [
            {"keyword": keyword, "search_volume": index * 10}
            for index, keyword in enumerate(
                ("alpha", "beta", "gamma", "delta", "empty", "missing"),
                1,
            )
        ]
        serps = [
            {
                "keyword": "alpha",
                "results": [
                    result(2, "https://example.com/two?utm_medium=x"),
                    result(1, "https://example.com/one"),
                ],
            },
            {
                "keyword": "beta",
                "results": [
                    result(1, "https://example.com/one#fragment"),
                    result(2, "https://example.com/two"),
                ],
            },
            {
                "keyword": "gamma",
                "results": [
                    result(1, "https://example.com/two?fbclid=tracking"),
                    result(2, "https://example.com/three?v=keep"),
                    result(3, "https://example.com/four"),
                ],
            },
            {"keyword": "delta", "results": [result(1, "https://other.example/page")]},
            {"keyword": "empty", "results": []},
        ]

        analysis = build_overlap_analysis(keywords, serps)

        identical = get_pair(analysis, "alpha", "beta")
        self.assertEqual((identical.shared_count, identical.jaccard), (2, 1.0))
        partial = get_pair(analysis, "alpha", "gamma")
        self.assertEqual((partial.size_a, partial.size_b, partial.shared_count), (2, 3, 1))
        self.assertAlmostEqual(partial.jaccard, 0.25)
        disjoint = get_pair(analysis, "alpha", "delta")
        self.assertEqual((disjoint.shared_count, disjoint.jaccard), (0, 0.0))
        self.assertEqual(analysis.excluded_keywords, ("empty", "missing"))
        self.assertNotIn("missing", analysis.evidence)


if __name__ == "__main__":
    unittest.main()
