from __future__ import annotations

import unittest

from x_downloader.nestdeck_runner import _to_wire_payload
from x_downloader.types import FormatOption, ResolvedMedia


class RunnerSerializationTests(unittest.TestCase):
    def test_to_wire_payload_adds_camel_case_aliases(self) -> None:
        payload = _to_wire_payload(
            ResolvedMedia(
                platform="youtube",
                url="https://www.youtube.com/watch?v=test",
                display_id="demo",
                title="Demo",
                uploader=None,
                duration_seconds=10.0,
                thumbnail_url=None,
                webpage_url="https://www.youtube.com/watch?v=test",
                requires_auth=False,
                formats=[
                    FormatOption(
                        format_id="18",
                        label="360p mp4",
                        ext="mp4",
                        protocol="https",
                        format_kind="MUXED",
                        width=640,
                        height=360,
                        fps=30.0,
                        video_codec="avc1.42001E",
                        audio_codec="mp4a.40.2",
                        video_bitrate_kbps=900.0,
                        audio_bitrate_kbps=128.0,
                        file_size_bytes=123456,
                    )
                ],
            )
        )

        self.assertEqual(payload["displayId"], "demo")
        self.assertEqual(payload["durationSeconds"], 10.0)
        self.assertEqual(payload["formats"][0]["formatId"], "18")
        self.assertEqual(payload["formats"][0]["formatKind"], "MUXED")
        self.assertEqual(payload["formats"][0]["videoCodec"], "avc1.42001E")
        self.assertEqual(payload["formats"][0]["audioBitrateKbps"], 128.0)
        self.assertEqual(payload["formats"][0]["fileSizeBytes"], 123456)


if __name__ == "__main__":
    unittest.main()
