from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.fetch_paper_images import (
    ImageCandidate,
    parse_candidates_from_html_url,
    score_candidate,
)


class FetchPaperImagesTests(unittest.TestCase):
    def test_relative_arxiv_image_path_does_not_duplicate_paper_id(self) -> None:
        html_url = "https://arxiv.org/html/2608.23011v1"
        html = b"""
        <html><body><figure class="ltx_figure">
          <img src="2608.23011v1/motivation_v2.png" alt="Method overview">
        </figure></body></html>
        """

        with patch(
            "scripts.fetch_paper_images.http_get",
            return_value=(html, "text/html", html_url),
        ):
            candidates, _ = parse_candidates_from_html_url(html_url)

        self.assertEqual(
            candidates[0].url,
            "https://arxiv.org/html/2608.23011v1/motivation_v2.png",
        )

    def test_arxiv_hostname_is_not_treated_as_a_bad_image_hint(self) -> None:
        candidate = ImageCandidate(
            url="https://arxiv.org/html/2608.23011v1/figures/overview.png",
            source="img",
            inside_figure=True,
            alt="Method overview",
        )

        self.assertEqual(score_candidate(candidate), 70)

    def test_bad_hint_in_path_is_still_penalized(self) -> None:
        good = ImageCandidate(
            url="https://arxiv.org/html/2608.23011v1/figures/overview.png",
            source="img",
            inside_figure=True,
        )
        logo = ImageCandidate(
            url="https://arxiv.org/static/arxiv-logo.png",
            source="img",
            inside_figure=True,
        )

        self.assertGreater(score_candidate(good), score_candidate(logo))
        self.assertLess(score_candidate(logo), 40)


if __name__ == "__main__":
    unittest.main()
