from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from x_downloader import api
from x_downloader.types import DownloadRequest, FormatOption, ResolvedMedia


class FormatMetadataTests(unittest.TestCase):
    def test_resolved_media_from_info_classifies_formats(self) -> None:
        resolved = api._resolved_media_from_info(
            "youtube",
            "https://www.youtube.com/watch?v=test",
            {
                "id": "demo",
                "display_id": "demo",
                "title": "Demo",
                "formats": [
                    {
                        "format_id": "18",
                        "format_note": "360p",
                        "ext": "mp4",
                        "protocol": "https",
                        "width": 640,
                        "height": 360,
                        "fps": 30,
                        "vcodec": "avc1.42001E",
                        "acodec": "mp4a.40.2",
                        "vbr": 900,
                        "abr": 128,
                        "filesize": 123456,
                    },
                    {
                        "format_id": "137",
                        "format_note": "1080p",
                        "ext": "mp4",
                        "protocol": "https",
                        "width": 1920,
                        "height": 1080,
                        "fps": 30,
                        "vcodec": "avc1.640028",
                        "acodec": "none",
                        "tbr": 2400,
                        "abr": 0,
                    },
                    {
                        "format_id": "140",
                        "format_note": "audio",
                        "ext": "m4a",
                        "protocol": "https",
                        "vcodec": "none",
                        "acodec": "mp4a.40.2",
                        "abr": 128,
                        "filesize_approx": 654321,
                    },
                ],
            },
        )

        self.assertEqual([option.format_kind for option in resolved.formats], ["MUXED", "VIDEO_ONLY", "AUDIO_ONLY"])
        self.assertEqual(resolved.formats[0].video_bitrate_kbps, 900)
        self.assertEqual(resolved.formats[1].video_bitrate_kbps, 2400)
        self.assertEqual(resolved.formats[2].audio_bitrate_kbps, 128)
        self.assertEqual(resolved.formats[2].file_size_bytes, 654321)

    def test_pick_default_format_prefers_audio_for_audio_only_mode(self) -> None:
        formats = [
            _format_option("137", "VIDEO_ONLY", height=1080),
            _format_option("18", "MUXED", height=360),
            _format_option("140", "AUDIO_ONLY", audio_bitrate_kbps=128),
        ]

        selected = api._pick_default_format(formats, "AUDIO_ONLY")

        self.assertIsNotNone(selected)
        self.assertEqual(selected.format_id, "140")


class DownloadPlanTests(unittest.TestCase):
    def test_video_with_audio_mode_merges_audio_for_video_only_format(self) -> None:
        expression = api._build_format_expression("VIDEO_WITH_AUDIO", _format_option("137", "VIDEO_ONLY", height=1080))
        self.assertEqual(expression, "137+bestaudio/best")

    def test_audio_only_mode_rejects_non_audio_format(self) -> None:
        with self.assertRaisesRegex(Exception, "audio-only format_id"):
            api._build_format_expression("AUDIO_ONLY", _format_option("18", "MUXED", height=360))

    def test_download_media_uses_probe_metadata_and_exact_audio_format(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "demo.m4a"
            output_file.write_bytes(b"demo-bytes")
            captured: dict[str, object] = {}

            class FakeYDL:
                def __init__(self, options: dict[str, object]) -> None:
                    captured["options"] = options

                def __enter__(self) -> "FakeYDL":
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:
                    return False

                def extract_info(self, url: str, download: bool) -> dict[str, object]:
                    captured["url"] = url
                    captured["download"] = download
                    return {
                        "title": "Demo",
                        "display_id": "demo",
                        "filepath": str(output_file),
                        "extractor": "youtube",
                        "id": "abc123",
                        "webpage_url": "https://www.youtube.com/watch?v=test",
                    }

            resolved = ResolvedMedia(
                platform="youtube",
                url="https://www.youtube.com/watch?v=test",
                display_id="demo",
                title="Demo",
                uploader="Uploader",
                duration_seconds=1.0,
                thumbnail_url=None,
                webpage_url="https://www.youtube.com/watch?v=test",
                requires_auth=False,
                formats=[_format_option("140", "AUDIO_ONLY", ext="m4a", audio_codec="mp4a.40.2", audio_bitrate_kbps=128)],
            )
            request = DownloadRequest(
                url="https://www.youtube.com/watch?v=test",
                output_dir=temp_dir,
                format_id="140",
                selection_mode="AUDIO_ONLY",
            )

            with patch("x_downloader.api.YoutubeDL", FakeYDL):
                with patch(
                    "x_downloader.api._probe_media",
                    return_value={
                        "has_video": False,
                        "has_audio": True,
                        "video_codec": None,
                        "audio_codec": "aac",
                        "width": None,
                        "height": None,
                        "fps": None,
                        "duration_seconds": 12.5,
                        "size_bytes": 10,
                    },
                ):
                    result = api.download_media(request, resolved_media=resolved)

        self.assertEqual(captured["options"]["format"], "140")
        self.assertEqual(captured["url"], "https://www.youtube.com/watch?v=test")
        self.assertEqual(result.mime_type, "audio/mp4")
        self.assertTrue(result.has_audio)
        self.assertFalse(result.has_video)
        self.assertEqual(result.audio_codec, "aac")
        self.assertEqual(result.info["selection_mode"], "AUDIO_ONLY")
        self.assertEqual(result.info["format_id"], "140")


def _format_option(
    format_id: str,
    format_kind: str,
    *,
    ext: str = "mp4",
    height: int | None = None,
    audio_codec: str | None = None,
    audio_bitrate_kbps: float | None = None,
) -> FormatOption:
    return FormatOption(
        format_id=format_id,
        label=format_id,
        ext=ext,
        protocol="https",
        format_kind=format_kind,
        width=None,
        height=height,
        fps=30.0 if height else None,
        video_codec="avc1.640028" if format_kind != "AUDIO_ONLY" else None,
        audio_codec=audio_codec,
        video_bitrate_kbps=1500.0 if height else None,
        audio_bitrate_kbps=audio_bitrate_kbps,
        file_size_bytes=1234,
    )


if __name__ == "__main__":
    unittest.main()
