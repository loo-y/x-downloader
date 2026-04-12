from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from x_downloader import cli


class ValidateUrlTests(unittest.TestCase):
    def test_validate_url_accepts_supported_platforms(self) -> None:
        cases = {
            "https://www.youtube.com/watch?v=test": "youtube",
            "https://youtu.be/abc123": "youtube",
            "https://x.com/user/status/123": "x",
            "https://twitter.com/user/status/456": "x",
            "https://missav.ws/cn/dass-648-chinese-subtitle": "missav",
        }

        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(cli.validate_url(url), expected)

    def test_validate_url_rejects_invalid_inputs(self) -> None:
        cases = {
            "https://example.com/test": "Only x.com, twitter.com, youtube.com, or missav.ws URLs are supported",
            "https://x.com/user/123": "X/Twitter URL must point to a specific post",
            "ftp://youtube.com/watch?v=test": "URL must start with http:// or https://",
        }

        for url, expected_message in cases.items():
            with self.subTest(url=url):
                with self.assertRaisesRegex(ValueError, expected_message):
                    cli.validate_url(url)


class ParserAndRunTests(unittest.TestCase):
    def test_help_text_mentions_supported_platforms(self) -> None:
        help_text = cli.build_parser().format_help()
        self.assertIn("Download videos from X/Twitter, YouTube, or MissAV", help_text)
        self.assertIn("X/Twitter, YouTube, or MissAV URL", help_text)

    def test_run_without_url_prints_updated_guidance(self) -> None:
        args = cli.build_parser().parse_args([])
        stderr = io.StringIO()

        with patch("x_downloader.cli.load_user_config", return_value={}):
            with redirect_stderr(stderr):
                exit_code = cli.run(args)

        self.assertEqual(exit_code, 2)
        self.assertIn("Missing URL. Pass an X/Twitter, YouTube, or MissAV URL", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
