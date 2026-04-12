from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from yt_dlp import DownloadError, YoutubeDL

from .missav import (
    MISSAV_HOSTS,
    MissavResolverError,
    resolve_video_source,
    should_use_browser_fallback,
)


SUPPORTED_HOSTS = {
    # X/Twitter
    "x.com",
    "www.x.com",
    "twitter.com",
    "www.twitter.com",
    "mobile.twitter.com",
    # YouTube
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
    # MissAV
    "missav.ws",
    "www.missav.ws",
}

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}


def get_config_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "x-downloader" / "config.json"
    return Path.home() / ".config" / "x-downloader" / "config.json"


def load_user_config() -> dict:
    config_path = get_config_path()
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_user_config(config: dict) -> Path:
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return config_path


def resolve_path_string(path_value: str) -> str:
    return str(Path(path_value).expanduser().resolve())


def get_chrome_root() -> Path:
    system = platform.system()

    if system == "Darwin":
        return Path.home() / "Library/Application Support/Google/Chrome"
    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "Google/Chrome/User Data"
        return Path.home() / "AppData/Local/Google/Chrome/User Data"
    if system == "Linux":
        config_home = os.environ.get("XDG_CONFIG_HOME")
        if config_home:
            return Path(config_home) / "google-chrome"
        return Path.home() / ".config/google-chrome"

    return Path()


def get_profile_cookies_db(profile_dir: Path) -> Path | None:
    for candidate in (profile_dir / "Network/Cookies", profile_dir / "Cookies"):
        if candidate.exists():
            return candidate
    return None


def get_chrome_profiles() -> list[dict]:
    chrome_root = get_chrome_root()
    local_state_path = chrome_root / "Local State"
    info_cache: dict[str, dict] = {}
    last_used: str | None = None

    if local_state_path.exists():
        try:
            local_state = json.loads(local_state_path.read_text())
            profile_data = local_state.get("profile", {})
            info_cache = profile_data.get("info_cache", {})
            last_used = profile_data.get("last_used")
        except (OSError, json.JSONDecodeError):
            pass

    profiles: list[dict] = []
    if not chrome_root.exists():
        return profiles

    for path in sorted(chrome_root.iterdir()):
        if not path.is_dir():
            continue
        cookies_db = get_profile_cookies_db(path)
        if cookies_db is None:
            continue
        info = info_cache.get(path.name, {})
        profiles.append(
            {
                "dir": path.name,
                "display_name": info.get("name") or path.name,
                "email": info.get("user_name") or "",
                "cookies_mtime": cookies_db.stat().st_mtime,
                "is_last_used": path.name == last_used,
                "has_x_auth": chrome_profile_has_x_auth(path),
            }
        )

    profiles.sort(
        key=lambda item: (item["has_x_auth"], item["is_last_used"], item["cookies_mtime"]),
        reverse=True,
    )
    return profiles


def chrome_profile_has_x_auth(profile_dir: Path) -> bool:
    cookies_db = get_profile_cookies_db(profile_dir)
    if cookies_db is None:
        return False

    temp_dir = Path(tempfile.mkdtemp(prefix="xdl-cookie-scan-"))
    temp_db = temp_dir / "Cookies"
    try:
        shutil.copy2(cookies_db, temp_db)
        conn = sqlite3.connect(temp_db)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 1
                FROM cookies
                WHERE (host_key LIKE '%x.com%' OR host_key LIKE '%twitter.com%')
                  AND name IN ('auth_token', 'ct0', 'twid')
                LIMIT 1
                """
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()
    except (OSError, sqlite3.DatabaseError):
        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def get_auto_browser_specs(args: argparse.Namespace) -> list[tuple[str, str]]:
    if args.cookies or args.cookies_from_browser:
        return []

    profiles = get_chrome_profiles()
    if args.chrome_profile:
        return [("chrome", args.chrome_profile)]
    return [("chrome", profile["dir"]) for profile in profiles]


def print_chrome_profiles() -> int:
    profiles = get_chrome_profiles()
    if not profiles:
        print(
            f"No local Chrome profiles with a Cookies database were found for {platform.system()}.",
            file=sys.stderr,
        )
        return 1

    for profile in profiles:
        markers = []
        if profile["is_last_used"]:
            markers.append("*")
        if profile["has_x_auth"]:
            markers.append("x")
        marker = "".join(markers) or " "
        email = f" | {profile['email']}" if profile["email"] else ""
        print(f"{marker} {profile['dir']} | {profile['display_name']}{email}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xdl",
        description="Download videos from X/Twitter, YouTube, or MissAV using yt-dlp. 使用 yt-dlp 下载 X/Twitter、YouTube 或 MissAV 视频。",
    )
    parser.add_argument("url", nargs="?", help="X/Twitter, YouTube, or MissAV URL。X/Twitter、YouTube 或 MissAV 链接。")
    parser.add_argument(
        "-o",
        "--output-dir",
        help="Directory to save files into. 保存目录；未传时优先使用已保存默认值，否则回退到 ./downloads",
    )
    parser.add_argument(
        "-n",
        "--name-template",
        default="%(uploader)s-%(id)s-%(title).80B.%(ext)s",
        help="yt-dlp output template for the filename. 文件名模板。",
    )
    parser.add_argument(
        "--cookies",
        help="Path to a Netscape cookies.txt file for logged-in downloads. cookies.txt 文件路径。",
    )
    parser.add_argument(
        "--set-default-download",
        help="Save the default download directory to %%APPDATA%%/x-downloader/config.json. 保存默认下载目录。",
    )
    parser.add_argument(
        "--clear-default-download",
        action="store_true",
        help="Clear the saved default download directory. 清除已保存的默认下载目录。",
    )
    parser.add_argument(
        "--set-default-cookies",
        help="Save the default cookies.txt path to %%APPDATA%%/x-downloader/config.json. 保存默认 cookies.txt 路径。",
    )
    parser.add_argument(
        "--clear-default-cookies",
        action="store_true",
        help="Clear the saved default cookies.txt path. 清除已保存的默认 cookies.txt 路径。",
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Print the current user config path and values. 显示当前用户配置路径和内容。",
    )
    parser.add_argument(
        "--cookies-from-browser",
        choices=["chrome", "chromium", "edge", "firefox", "safari", "brave"],
        help="Load cookies directly from a local browser profile via yt-dlp. 直接从浏览器读取登录态。",
    )
    parser.add_argument(
        "--chrome-profile",
        help="Chrome profile directory name such as 'Default' or 'Profile 5' on macOS/Windows/Linux. Chrome profile 名。",
    )
    parser.add_argument(
        "--list-chrome-profiles",
        action="store_true",
        help="List local Chrome profiles and exit. 列出本机 Chrome profiles；'*' 表示最近使用。",
    )
    parser.add_argument(
        "--proxy",
        help="Proxy URL to pass through to yt-dlp, e.g. http://127.0.0.1:7890。代理地址。",
    )
    parser.add_argument(
        "--use-env-proxy",
        action="store_true",
        help="Honor proxy environment variables instead of forcing a direct connection. 使用环境变量中的代理。",
    )
    parser.add_argument(
        "--audio-only",
        action="store_true",
        help="Download audio only instead of the full video. 仅下载音频。",
    )
    parser.add_argument(
        "--write-thumbnail",
        action="store_true",
        help="Also download the post thumbnail if available. 同时下载缩略图。",
    )
    parser.add_argument(
        "--write-info-json",
        action="store_true",
        help="Also save yt-dlp metadata as JSON. 同时保存元数据 JSON。",
    )
    parser.add_argument(
        "--clip-start",
        help="Clip start time after download, e.g. 10, 00:00:10, or 1:23。下载后裁切起始时间。",
    )
    parser.add_argument(
        "--clip-end",
        help="Clip end time after download, e.g. 40 or 00:00:40。下载后裁切结束时间。",
    )
    parser.add_argument(
        "--clip-duration",
        help="Clip duration after download, e.g. 10 or 00:00:10。下载后裁切时长。",
    )
    parser.add_argument(
        "--keep-original",
        action="store_true",
        help="Keep the full downloaded file when generating a clipped output. 裁切后保留原始完整文件。",
    )
    return parser


def validate_url(url: str) -> str:
    """Validate URL and return platform type ('x', 'youtube', or 'missav')."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL must start with http:// or https://")

    host = parsed.netloc.lower()
    if host not in SUPPORTED_HOSTS:
        raise ValueError("Only x.com, twitter.com, youtube.com, or missav.ws URLs are supported")

    if host in YOUTUBE_HOSTS:
        return "youtube"
    if host in MISSAV_HOSTS:
        return "missav"

    path = parsed.path.strip("/")
    if "/status/" not in f"/{path}/":
        raise ValueError("X/Twitter URL must point to a specific post")
    return "x"


def build_ydl_options(
    args: argparse.Namespace,
    browser_spec: tuple[str, str] | tuple[str] | None = None,
    http_headers: dict[str, str] | None = None,
) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    format_selector = "bestaudio/best" if args.audio_only else "bestvideo*+bestaudio/best"

    opts = {
        "outtmpl": str(output_dir / args.name_template),
        "format": format_selector,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
        "writesubtitles": False,
        "writeautomaticsub": False,
        "writethumbnail": args.write_thumbnail,
        "writeinfojson": args.write_info_json,
        "restrictfilenames": False,
    }

    if args.cookies:
        opts["cookiefile"] = str(Path(args.cookies).expanduser().resolve())
    if args.cookies_from_browser:
        if args.cookies_from_browser == "chrome" and args.chrome_profile:
            opts["cookiesfrombrowser"] = ("chrome", args.chrome_profile)
        else:
            opts["cookiesfrombrowser"] = (args.cookies_from_browser,)
    elif browser_spec:
        opts["cookiesfrombrowser"] = browser_spec
    if args.proxy:
        opts["proxy"] = args.proxy
    elif not args.use_env_proxy:
        # yt-dlp inherits proxy environment variables by default.
        # Force a direct connection unless the user opts into env-based proxies.
        opts["proxy"] = ""
    if http_headers:
        opts["http_headers"] = http_headers

    return opts


def validate_clip_args(args: argparse.Namespace) -> None:
    if args.clip_end and args.clip_duration:
        raise ValueError("--clip-end and --clip-duration cannot be used together")

    clip_values = [args.clip_start, args.clip_end, args.clip_duration]
    if any(value is not None for value in clip_values):
        if shutil.which("ffmpeg") is None:
            raise ValueError("ffmpeg is required for clipping but was not found in PATH")

    if args.clip_duration is not None and args.clip_duration == "0":
        raise ValueError("--clip-duration must be greater than 0")


def build_clip_output_path(input_path: Path, args: argparse.Namespace) -> Path:
    start = args.clip_start or "0"
    end_part = f"end-{args.clip_end}" if args.clip_end else ""
    dur_part = f"dur-{args.clip_duration}" if args.clip_duration else ""
    parts = [part for part in [f"start-{start}", end_part, dur_part] if part]
    suffix = ".".join(parts).replace(":", "-")
    extension = ".m4a" if args.audio_only else ".mp4"
    return input_path.with_name(f"{input_path.stem}.clip.{suffix}{extension}")


def clip_media(input_path: Path, args: argparse.Namespace) -> Path:
    output_path = build_clip_output_path(input_path, args)
    command = ["ffmpeg", "-y", "-i", str(input_path)]

    if args.clip_start:
        command.extend(["-ss", args.clip_start])
    if args.clip_end:
        command.extend(["-to", args.clip_end])
    if args.clip_duration:
        command.extend(["-t", args.clip_duration])

    if args.audio_only:
        command.extend(["-vn", "-c:a", "aac"])
    else:
        command.extend(
            [
                "-map",
                "0:v:0?",
                "-map",
                "0:a:0?",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
            ]
        )

    command.append(str(output_path))

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else str(exc)
        raise RuntimeError(f"ffmpeg clipping failed: {stderr}") from exc

    if not args.keep_original:
        input_path.unlink(missing_ok=True)

    return output_path


def is_auth_related_error(message: str) -> bool:
    lowered = message.lower()
    return (
        "login" in lowered
        or "cookie" in lowered
        or "guest token" in lowered
        or "bad guest token" in lowered
        or "not authorized" in lowered
        or "authorization" in lowered
    )


def is_browser_cookie_decrypt_error(message: str) -> bool:
    lowered = message.lower()
    return (
        "failed to decrypt with dpapi" in lowered
        or "app-bound encryption" in lowered
        or "failed to decrypt" in lowered and "cookie" in lowered
    )


def build_cookies_fallback_hint(args: argparse.Namespace) -> str:
    if not args.url:
        return "--cookies /path/to/cookies.txt"
    return f'xdl "{args.url}" --cookies /path/to/cookies.txt'


def show_config(config: dict) -> int:
    print(f"Config path: {get_config_path()}")
    if not config:
        print("{}")
        return 0
    print(json.dumps(config, ensure_ascii=False, indent=2))
    return 0


def apply_config_actions(args: argparse.Namespace, config: dict) -> int | None:
    changed = False

    if args.set_default_download:
        config["default_download_dir"] = resolve_path_string(args.set_default_download)
        changed = True

    if args.clear_default_download:
        config.pop("default_download_dir", None)
        changed = True

    if args.set_default_cookies:
        cookies_path = Path(args.set_default_cookies).expanduser().resolve()
        if not cookies_path.is_file():
            print(
                f"Invalid arguments: cookies file does not exist: {cookies_path}",
                file=sys.stderr,
            )
            return 2
        config["default_cookies"] = str(cookies_path)
        changed = True

    if args.clear_default_cookies:
        config.pop("default_cookies", None)
        changed = True

    if changed:
        config_path = save_user_config(config)
        print(f"Saved config to: {config_path}")

    if args.show_config or changed:
        return show_config(config)

    return None


def resolve_runtime_defaults(args: argparse.Namespace, config: dict) -> None:
    if not args.output_dir:
        args.output_dir = config.get("default_download_dir") or "downloads"
    if not args.cookies and not args.cookies_from_browser:
        default_cookies = config.get("default_cookies")
        if default_cookies:
            args.cookies = default_cookies


def try_download(
    args: argparse.Namespace,
    browser_spec: tuple[str, str] | tuple[str] | None = None,
    download_url: str | None = None,
    http_headers: dict[str, str] | None = None,
) -> dict:
    with YoutubeDL(build_ydl_options(args, browser_spec=browser_spec, http_headers=http_headers)) as ydl:
        return ydl.extract_info(download_url or args.url, download=True)


def try_download_missav(args: argparse.Namespace) -> tuple[dict | None, str]:
    try:
        return try_download(args), ""
    except DownloadError as exc:
        error_message = str(exc)
        if not should_use_browser_fallback(error_message):
            return None, error_message

    print(
        "MissAV page access was blocked by Cloudflare. Retrying via local Chrome to resolve the video stream...",
        file=sys.stderr,
    )
    try:
        video_source = resolve_video_source(
            args.url,
            proxy=args.proxy,
            use_env_proxy=args.use_env_proxy,
        )
    except MissavResolverError as exc:
        return None, (
            "MissAV browser fallback failed: "
            f"{exc}\n"
            "请确认本机已安装可用的 Chrome，并且该页面可以在本机 Chrome 中正常打开。"
        )

    print(f"Resolved MissAV stream URL via local Chrome: {video_source.manifest_url}", file=sys.stderr)
    try:
        return (
            try_download(
                args,
                download_url=video_source.manifest_url,
                http_headers=video_source.http_headers,
            ),
            "",
        )
    except DownloadError as exc:
        return None, str(exc)


def run(args: argparse.Namespace) -> int:
    config = load_user_config()

    config_result = apply_config_actions(args, config)
    if config_result is not None:
        return config_result

    resolve_runtime_defaults(args, config)

    if args.list_chrome_profiles:
        return print_chrome_profiles()

    if not args.url:
        print("Missing URL. Pass an X/Twitter, YouTube, or MissAV URL or use --list-chrome-profiles.", file=sys.stderr)
        return 2

    try:
        platform_name = validate_url(args.url)
    except ValueError as exc:
        print(f"Invalid URL: {exc}", file=sys.stderr)
        return 2
    try:
        validate_clip_args(args)
    except ValueError as exc:
        print(f"Invalid arguments: {exc}", file=sys.stderr)
        return 2

    downloaded_info: dict | None = None
    message = ""
    if platform_name == "missav":
        downloaded_info, message = try_download_missav(args)
    else:
        auto_browser_specs = get_auto_browser_specs(args)
        if auto_browser_specs:
            last_error: DownloadError | None = None
            for index, spec in enumerate(auto_browser_specs):
                try:
                    if index > 0:
                        print(
                            f"Retrying with Chrome profile: {spec[1]}",
                            file=sys.stderr,
                        )
                    downloaded_info = try_download(args, browser_spec=spec)
                    break
                except DownloadError as exc:
                    last_error = exc
                    if not is_auth_related_error(str(exc)):
                        break

            if downloaded_info is None and last_error is not None:
                message = str(last_error)
            elif downloaded_info is None:
                message = "No Chrome profile could be used for X authentication."
        else:
            try:
                downloaded_info = try_download(args)
            except DownloadError as exc:
                message = str(exc)

    if message:
        if "Requested format is not available" in message:
            print(
                "Download failed: the post may not contain a downloadable video or the format is unavailable.",
                file=sys.stderr,
            )
        elif is_browser_cookie_decrypt_error(message):
            print(
                "Download failed: the browser cookies could not be decrypted on this machine.\n"
                "On Windows, fully quit Chrome and try again. If it still fails, export X/Twitter cookies "
                f"to a Netscape cookies.txt file and run:\n{build_cookies_fallback_hint(args)}\n"
                "下载失败：当前机器无法解密浏览器 cookies。\n"
                "Windows 下请先彻底退出 Chrome 后重试。如果仍然失败，请导出 X/Twitter 的 "
                f"Netscape cookies.txt 文件，然后执行：\n{build_cookies_fallback_hint(args)}",
                file=sys.stderr,
            )
        elif is_auth_related_error(message):
            print(
                "Download failed: X rejected access for this post. The CLI already auto-tried Chrome profiles with X login cookies. Try --chrome-profile 'Profile 5', --cookies-from-browser chrome, or --cookies /path/to/cookies.txt",
                file=sys.stderr,
            )
        elif platform_name == "missav":
            print(
                f"Download failed: {message}\n"
                "MissAV 站点会触发 Cloudflare/播放器脚本限制。CLI 会优先尝试直连，失败后自动改用本机 Chrome 解析真实视频流地址。",
                file=sys.stderr,
            )
        else:
            print(f"Download failed: {message}", file=sys.stderr)
        return 1

    if any(value is not None for value in [args.clip_start, args.clip_end, args.clip_duration]):
        filepath = downloaded_info.get("filepath") if downloaded_info else None
        if not filepath:
            requested_downloads = downloaded_info.get("requested_downloads") if downloaded_info else None
            if requested_downloads:
                filepath = requested_downloads[0].get("filepath")
        if not filepath:
            print(
                "Download succeeded but the final file path could not be resolved for clipping.",
                file=sys.stderr,
            )
            return 1
        try:
            clipped_path = clip_media(Path(filepath), args)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"Clipped output saved to: {clipped_path}")

    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
