from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from x_downloader import cli
from x_downloader.types import DownloadResult


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
                with self.assertRaisesRegex(Exception, expected_message):
                    cli.validate_url(url)


class ParserAndRunTests(unittest.TestCase):
    def test_help_text_mentions_supported_platforms(self) -> None:
        help_text = cli.build_parser().format_help()
        self.assertIn("Download videos from X/Twitter, YouTube, or MissAV", help_text)
        self.assertIn("X/Twitter, YouTube, or MissAV URL", help_text)
        self.assertIn("--selection-mode", help_text)
        self.assertIn("--format-id", help_text)

    def test_build_download_request_maps_compatibility_flags(self) -> None:
        args = cli.build_parser().parse_args(
            [
                "https://www.youtube.com/watch?v=test",
                "--format-id",
                "140",
                "--audio-only",
            ]
        )

        request = cli._build_download_request(args)

        self.assertEqual(request.format_id, "140")
        self.assertEqual(request.selection_mode, "AUDIO_ONLY")

    def test_run_rejects_conflicting_selection_flags(self) -> None:
        args = cli.build_parser().parse_args(
            [
                "https://www.youtube.com/watch?v=test",
                "--audio-only",
                "--video-only",
            ]
        )
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            exit_code = cli.run(args)

        self.assertEqual(exit_code, 2)
        self.assertIn("--audio-only and --video-only cannot be used together", stderr.getvalue())

    def test_run_without_url_prints_updated_guidance(self) -> None:
        args = cli.build_parser().parse_args([])
        stderr = io.StringIO()

        with patch("x_downloader.cli.load_user_config", return_value={}):
            with redirect_stderr(stderr):
                exit_code = cli.run(args)

        self.assertEqual(exit_code, 2)
        self.assertIn("Missing URL. Pass an X/Twitter, YouTube, or MissAV URL", stderr.getvalue())

    def test_run_prints_saved_file_path_on_success(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "video.mp4"
            output_file.write_bytes(b"demo")
            args = cli.build_parser().parse_args(
                ["https://www.youtube.com/watch?v=test", "--output-dir", temp_dir]
            )
            stdout = io.StringIO()

            with patch("x_downloader.cli.load_user_config", return_value={}):
                with patch(
                    "x_downloader.cli.download_media",
                    return_value=DownloadResult(
                        platform="youtube",
                        file_path=str(output_file),
                        title="Demo",
                        display_id="demo",
                        mime_type="video/mp4",
                        ext="mp4",
                        size_bytes=4,
                    ),
                ):
                    with redirect_stdout(stdout):
                        exit_code = cli.run(args)

        self.assertEqual(exit_code, 0)
        self.assertIn("Saved to:", stdout.getvalue())
