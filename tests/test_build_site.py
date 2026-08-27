from __future__ import annotations

import unittest

from scripts.build_site import generate_app_js


class BuildSiteTests(unittest.TestCase):
    def test_homepage_data_fetch_bypasses_stale_cache(self) -> None:
        app_js = generate_app_js()
        self.assertIn("assets/data.json?v=", app_js)
        self.assertIn("Date.now()", app_js)
        self.assertIn("cache: 'no-store'", app_js)


if __name__ == "__main__":
    unittest.main()
