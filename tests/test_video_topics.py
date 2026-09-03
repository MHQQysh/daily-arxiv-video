from __future__ import annotations

import unittest

from scripts.video_topics import (
    ALLOWED_PRIMARY_CATEGORIES,
    FALLBACK_QUERY,
    PRIMARY_QUERY,
    is_relevant_video_paper,
    relevance_score,
)


class VideoTopicTests(unittest.TestCase):
    def test_queries_and_categories_are_video_specific(self) -> None:
        self.assertEqual(PRIMARY_QUERY, "ti:video")
        self.assertEqual(FALLBACK_QUERY, "all:video")
        self.assertIn("cs.CV", ALLOWED_PRIMARY_CATEGORIES)
        self.assertNotIn("physics.gen-ph", ALLOWED_PRIMARY_CATEGORIES)

    def test_title_video_is_always_relevant(self) -> None:
        self.assertTrue(is_relevant_video_paper("Efficient Video Reasoning", "A new benchmark."))

    def test_strong_abstract_topic_can_fill_fallback(self) -> None:
        abstract = "We study video generation and video diffusion with a temporal video model."
        self.assertTrue(is_relevant_video_paper("Efficient Temporal Models", abstract))
        self.assertGreaterEqual(relevance_score("Efficient Temporal Models", abstract), 4)

    def test_repeated_video_evidence_with_one_strong_topic_can_fill_fallback(self) -> None:
        abstract = (
            "We repurpose pretrained video diffusion models. "
            "The video model predicts future observations and actions."
        )
        self.assertEqual(relevance_score("Spatially Aware World Action Model", abstract), 3)
        self.assertTrue(is_relevant_video_paper("Spatially Aware World Action Model", abstract))

    def test_single_incidental_video_mention_is_rejected(self) -> None:
        self.assertFalse(is_relevant_video_paper("Image Classification", "A demo video is available."))

    def test_non_video_temporal_paper_is_rejected(self) -> None:
        self.assertFalse(
            is_relevant_video_paper(
                "Temporal Forecasting for Sensor Networks",
                "We forecast multivariate industrial sensor streams.",
            )
        )


if __name__ == "__main__":
    unittest.main()
