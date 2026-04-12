from __future__ import annotations

import io
import unittest

from x_downloader.missav import (
    build_video_source,
    build_noninteractive_quality_error,
    build_quality_options,
    choose_manifest_url,
    extract_stream_urls_from_scripts,
    prompt_for_quality_choice,
    select_quality_option,
    should_use_browser_fallback,
)


PACKED_MISSAV_SCRIPT = r"""
eval(function(p,a,c,k,e,d){e=function(c){return c.toString(36)};
if(!''.replace(/^/,String)){while(c--){d[c.toString(a)]=k[c]||c.toString(a)}
k=[function(e){return d[e]}];e=function(){return'\\w+'};c=1};
while(c--){if(k[c]){p=p.replace(new RegExp('\\b'+e(c)+'\\b','g'),k[c])}}
return p}('e=\'8://7.6/5-4-3-2-1/d.0\';c=\'8://7.6/5-4-3-2-1/a/9.0\';b=\'8://7.6/5-4-3-2-1/a/9.0\';',15,15,'m3u8|959dc2149323|92d6|4dec|e9a2|599fceb0|com|surrit|https|video|720p|source1280|source842|playlist|source'.split('|'),0,{}))
"""


class MissavHelperTests(unittest.TestCase):
    def test_extract_stream_urls_from_packed_script(self) -> None:
        streams = extract_stream_urls_from_scripts(PACKED_MISSAV_SCRIPT)
        self.assertEqual(
            streams["source"],
            "https://surrit.com/599fceb0-e9a2-4dec-92d6-959dc2149323/playlist.m3u8",
        )
        self.assertEqual(
            streams["source842"],
            "https://surrit.com/599fceb0-e9a2-4dec-92d6-959dc2149323/720p/video.m3u8",
        )

    def test_choose_manifest_url_prefers_master_playlist(self) -> None:
        chosen = choose_manifest_url(
            [
                "https://surrit.com/example/720p/video.m3u8",
                "https://surrit.com/example/playlist.m3u8",
            ]
        )
        self.assertEqual(chosen, "https://surrit.com/example/playlist.m3u8")

    def test_should_use_browser_fallback_for_cloudflare_block(self) -> None:
        self.assertTrue(
            should_use_browser_fallback(
                "ERROR: [generic] Got HTTP Error 403 caused by Cloudflare anti-bot challenge"
            )
        )
        self.assertFalse(should_use_browser_fallback("ERROR: Requested format is not available"))

    def test_build_video_source_sets_referer(self) -> None:
        source = build_video_source(
            "https://missav.ws/cn/dass-648-chinese-subtitle",
            "https://surrit.com/example/playlist.m3u8",
            "Mozilla/5.0 Test",
            "MissAV title",
        )
        self.assertEqual(source.http_headers["Referer"], "https://missav.ws/cn/dass-648-chinese-subtitle")
        self.assertEqual(source.http_headers["User-Agent"], "Mozilla/5.0 Test")

    def test_quality_options_assign_low_medium_high(self) -> None:
        options = build_quality_options(
            [
                {"height": 360, "format_id": "360", "url": "https://example.com/360.m3u8"},
                {"height": 480, "format_id": "480", "url": "https://example.com/480.m3u8"},
                {"height": 720, "format_id": "720", "url": "https://example.com/720.m3u8"},
            ],
            {"Referer": "https://missav.ws/cn/test"},
        )
        self.assertEqual([(option.height, option.label) for option in options], [(360, "low"), (480, "medium"), (720, "high")])

    def test_select_quality_option_uses_alias(self) -> None:
        options = build_quality_options(
            [
                {"height": 360, "format_id": "360", "url": "https://example.com/360.m3u8"},
                {"height": 480, "format_id": "480", "url": "https://example.com/480.m3u8"},
                {"height": 720, "format_id": "720", "url": "https://example.com/720.m3u8"},
            ],
            {"Referer": "https://missav.ws/cn/test"},
        )
        self.assertEqual(select_quality_option(options, "high").height, 720)
        self.assertEqual(select_quality_option(options, "medium").height, 480)

    def test_prompt_for_quality_choice_returns_selected_option(self) -> None:
        options = build_quality_options(
            [
                {"height": 360, "format_id": "360", "url": "https://example.com/360.m3u8"},
                {"height": 720, "format_id": "720", "url": "https://example.com/720.m3u8"},
            ],
            {"Referer": "https://missav.ws/cn/test"},
        )
        output = io.StringIO()
        selected = prompt_for_quality_choice(options, input_func=lambda _prompt: "2", output=output)
        self.assertEqual(selected.height, 720)
        self.assertIn("MissAV supports the following resolutions", output.getvalue())

    def test_noninteractive_quality_error_lists_supported_heights(self) -> None:
        options = build_quality_options(
            [
                {"height": 360, "format_id": "360", "url": "https://example.com/360.m3u8"},
                {"height": 720, "format_id": "720", "url": "https://example.com/720.m3u8"},
            ],
            {"Referer": "https://missav.ws/cn/test"},
        )
        message = build_noninteractive_quality_error(options)
        self.assertIn("360p", message)
        self.assertIn("720p", message)
        self.assertIn("--quality low|medium|high", message)


if __name__ == "__main__":
    unittest.main()
