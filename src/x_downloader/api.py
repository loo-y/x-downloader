from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

try:
    from yt_dlp import DownloadError, YoutubeDL
except ModuleNotFoundError:  # pragma: no cover - exercised only in dependency-missing environments.
    class DownloadError(RuntimeError):
        pass

    YoutubeDL = None

from .errors import CancelledError, CredentialError, DependencyError, DownloadFailure, ResolveError, ValidationError
from .missav import (
    MISSAV_HOSTS,
    MissavResolverError,
    build_noninteractive_quality_error,
    extract_manifest_formats,
    resolve_video_source,
    select_quality_option,
)
from .types import (
    CredentialCheck,
    DownloadProgress,
    DownloadRequest,
    DownloadResult,
    FormatOption,
    PlatformKey,
    ResolveRequest,
    ResolvedMedia,
    SelectionMode,
    ensure_directory,
)

SUPPORTED_HOSTS = {
    "x.com",
    "www.x.com",
    "twitter.com",
    "www.twitter.com",
    "mobile.twitter.com",
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
    *MISSAV_HOSTS,
}

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}
X_COOKIE_FIELDS = ("auth_token", "ct0", "twid")
YOUTUBE_COOKIE_FIELDS = ("SID", "SAPISID", "__Secure-3PSID", "LOGIN_INFO")


@dataclass(frozen=True)
class DownloadPlan:
    selected_format: FormatOption | None
    format_expression: str | None
    download_url: str
    http_headers: dict[str, str] | None


def validate_url(url: str) -> PlatformKey:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValidationError("URL must start with http:// or https://")

    host = parsed.netloc.lower()
    if host not in SUPPORTED_HOSTS:
        raise ValidationError("Only x.com, twitter.com, youtube.com, or missav.ws URLs are supported")

    if host in YOUTUBE_HOSTS:
        return "youtube"
    if host in MISSAV_HOSTS:
        return "missav"

    path = parsed.path.strip("/")
    if "/status/" not in f"/{path}/":
        raise ValidationError("X/Twitter URL must point to a specific post")
    return "x"


def validate_credential(platform: PlatformKey, cookie_file: str) -> CredentialCheck:
    path = Path(cookie_file).expanduser().resolve()
    if not path.is_file():
        raise CredentialError(f"Cookie file does not exist: {path}")

    rows = _load_cookie_rows(path)
    if not rows:
        raise CredentialError("cookies.txt is empty or malformed.")

    if platform == "missav":
        return CredentialCheck(
            platform=platform,
            state="unsupported",
            message="MissAV does not use personal cookies in x-downloader container mode.",
            account_hint=None,
            checked_fields=[],
        )

    required_fields = X_COOKIE_FIELDS if platform == "x" else YOUTUBE_COOKIE_FIELDS
    relevant_hosts = {"x.com", ".x.com", "twitter.com", ".twitter.com"} if platform == "x" else {
        "youtube.com",
        ".youtube.com",
    }

    matched_names: set[str] = set()
    account_hint: str | None = None
    for host, name, value in rows:
        normalized_host = host.lower()
        if not any(token in normalized_host for token in relevant_hosts):
            continue
        if name in required_fields and value:
            matched_names.add(name)
        if not account_hint and name in {"twid", "LOGIN_INFO", "VISITOR_INFO1_LIVE"} and value:
            account_hint = _mask_value(value)

    missing = [field for field in required_fields[:2] if field not in matched_names]
    if missing:
        raise CredentialError(
            "Cookie file is missing required login fields.",
            details={"missing_fields": missing},
        )

    return CredentialCheck(
        platform=platform,
        state="valid",
        message="Cookie file looks usable for authenticated downloads.",
        account_hint=account_hint,
        checked_fields=sorted(matched_names),
    )


def resolve_media(request: ResolveRequest) -> ResolvedMedia:
    platform = validate_url(request.url)
    _require_yt_dlp()
    try:
        if platform == "missav":
            return resolve_missav_stream(request)
        info = _extract_info(request, request.url, download=False)
        return _resolved_media_from_info(platform, request.url, info)
    except (DownloadError, MissavResolverError) as exc:
        raise ResolveError(str(exc)) from exc


def download_media(
    request: DownloadRequest,
    *,
    resolved_media: ResolvedMedia | None = None,
    progress_hook: Callable[[DownloadProgress], None] | None = None,
    cancellation_check: Callable[[], bool] | None = None,
) -> DownloadResult:
    platform = validate_url(request.url)
    _require_yt_dlp()
    _validate_clip_args(request)
    output_dir = ensure_directory(request.output_dir)
    resolved = resolved_media or resolve_media(
        ResolveRequest(
            url=request.url,
            cookie_file=request.cookie_file,
            proxy=request.proxy,
            use_env_proxy=request.use_env_proxy,
            cookies_from_browser=request.cookies_from_browser,
            chrome_profile=request.chrome_profile,
            chrome_binary=request.chrome_binary,
        )
    )

    if progress_hook is not None:
        progress_hook(
            DownloadProgress(
                phase="resolving",
                downloaded_bytes=None,
                total_bytes=None,
                speed_bytes_per_second=None,
                eta_seconds=None,
                percent=None,
                filename=None,
            )
        )

    selected_format = _select_format(resolved, request)
    plan = _build_download_plan(resolved, request, selected_format)

    class _Cancelled(Exception):
        pass

    def _yt_progress(progress: dict[str, object]) -> None:
        if cancellation_check and cancellation_check():
            raise _Cancelled()
        if progress_hook is None:
            return
        status = str(progress.get("status", "downloading"))
        total = _coerce_int(progress.get("total_bytes")) or _coerce_int(progress.get("total_bytes_estimate"))
        downloaded = _coerce_int(progress.get("downloaded_bytes"))
        percent = None
        if downloaded is not None and total:
            percent = max(0.0, min(100.0, downloaded / total * 100))
        phase = "postprocessing" if status == "finished" else "downloading"
        progress_hook(
            DownloadProgress(
                phase=phase,
                downloaded_bytes=downloaded,
                total_bytes=total,
                speed_bytes_per_second=_coerce_float(progress.get("speed")),
                eta_seconds=_coerce_float(progress.get("eta")),
                percent=percent,
                filename=_coerce_string(progress.get("filename")),
            )
        )

    ydl_options = _build_ydl_options(request, output_dir=output_dir, http_headers=plan.http_headers)
    if plan.format_expression:
        ydl_options["format"] = plan.format_expression
    ydl_options["progress_hooks"] = [_yt_progress]

    try:
        with YoutubeDL(ydl_options) as ydl:
            info = ydl.extract_info(plan.download_url, download=True)
    except _Cancelled as exc:
        raise CancelledError() from exc
    except DownloadError as exc:
        message = str(exc)
        if platform == "missav" and "multiple resolutions" in message.lower():
            raise DownloadFailure(build_noninteractive_quality_error(resolved.formats)) from exc
        raise DownloadFailure(message) from exc

    filepath = _resolve_output_filepath(info)
    if filepath is None:
        raise DownloadFailure("Download finished but the final file path could not be resolved.")

    final_path = Path(filepath)
    if any(value is not None for value in (request.clip_start, request.clip_end, request.clip_duration)):
        try:
            final_path = _clip_media(final_path, request)
        except RuntimeError as exc:
            raise DownloadFailure(str(exc)) from exc

    if progress_hook is not None:
        final_size = final_path.stat().st_size if final_path.exists() else None
        progress_hook(
            DownloadProgress(
                phase="finished",
                downloaded_bytes=final_size,
                total_bytes=final_size,
                speed_bytes_per_second=None,
                eta_seconds=0.0,
                percent=100.0,
                filename=str(final_path),
            )
        )

    probed = _probe_media(final_path)

    return DownloadResult(
        platform=platform,
        file_path=str(final_path),
        title=_coerce_string(info.get("title")) or resolved.title,
        display_id=_coerce_string(info.get("display_id")) or resolved.display_id,
        mime_type=_guess_mime_type(final_path.suffix, has_video=probed["has_video"], has_audio=probed["has_audio"]),
        ext=final_path.suffix[1:] if final_path.suffix else None,
        has_video=probed["has_video"],
        has_audio=probed["has_audio"],
        video_codec=probed["video_codec"],
        audio_codec=probed["audio_codec"],
        width=probed["width"],
        height=probed["height"],
        fps=probed["fps"],
        duration_seconds=probed["duration_seconds"],
        size_bytes=probed["size_bytes"],
        info={
            "extractor": _coerce_string(info.get("extractor")),
            "id": _coerce_string(info.get("id")),
            "webpage_url": _coerce_string(info.get("webpage_url")) or request.url,
            "selection_mode": request.selection_mode,
            "format_id": selected_format.format_id if selected_format else request.format_id,
            "probe": {
                "has_video": probed["has_video"],
                "has_audio": probed["has_audio"],
                "video_codec": probed["video_codec"],
                "audio_codec": probed["audio_codec"],
                "width": probed["width"],
                "height": probed["height"],
                "fps": probed["fps"],
                "duration_seconds": probed["duration_seconds"],
                "size_bytes": probed["size_bytes"],
            },
        },
    )


def resolve_missav_stream(request: ResolveRequest) -> ResolvedMedia:
    """Resolve a MissAV page through the isolated Chromium-compatible path."""
    if validate_url(request.url) != "missav":
        raise ValidationError("resolve_missav_stream requires a MissAV video URL")
    source = resolve_video_source(
        request.url,
        proxy=request.proxy,
        use_env_proxy=request.use_env_proxy,
        chrome_profile=request.chrome_profile,
        chrome_binary=request.chrome_binary,
    )
    quality_options = extract_manifest_formats(
        source,
        proxy=request.proxy,
        use_env_proxy=request.use_env_proxy,
    )
    formats = [
        FormatOption(
            format_id=option.format_id,
            label=f"{option.height}p{f' ({option.label})' if option.label else ''}",
            ext="mp4",
            protocol="m3u8",
            format_kind="MUXED",
            width=None,
            height=option.height,
            fps=None,
            video_codec=None,
            audio_codec=None,
            video_bitrate_kbps=None,
            audio_bitrate_kbps=None,
            file_size_bytes=None,
            manifest_url=option.manifest_url,
            http_headers=option.http_headers,
            quality_hint=option.label or None,
        )
        for option in quality_options
    ]
    return ResolvedMedia(
        platform="missav",
        url=request.url,
        display_id=source.display_id,
        title=source.page_title or source.display_id,
        uploader=None,
        duration_seconds=None,
        thumbnail_url=None,
        webpage_url=source.page_url,
        requires_auth=False,
        formats=formats,
        raw_info={"manifest_url": source.manifest_url},
    )


def _resolved_media_from_info(platform: PlatformKey, url: str, info: dict[str, object]) -> ResolvedMedia:
    formats: list[FormatOption] = []
    raw_formats = info.get("formats")
    if isinstance(raw_formats, list):
        for raw in raw_formats:
            if not isinstance(raw, dict):
                continue
            label_bits = [
                _coerce_string(raw.get("format_note")),
                f"{raw['height']}p" if isinstance(raw.get("height"), int) else None,
                _coerce_string(raw.get("ext")),
            ]
            label = " ".join(bit for bit in label_bits if bit) or (_coerce_string(raw.get("format")) or "Unknown")
            audio_codec = _normalize_codec(_coerce_string(raw.get("acodec")))
            video_codec = _normalize_codec(_coerce_string(raw.get("vcodec")))
            formats.append(
                FormatOption(
                    format_id=_coerce_string(raw.get("format_id")) or "best",
                    label=label,
                    ext=_coerce_string(raw.get("ext")),
                    protocol=_coerce_string(raw.get("protocol")),
                    format_kind=_detect_format_kind(
                        video_codec=video_codec,
                        audio_codec=audio_codec,
                        width=_coerce_int(raw.get("width")),
                        height=_coerce_int(raw.get("height")),
                    ),
                    width=_coerce_int(raw.get("width")),
                    height=_coerce_int(raw.get("height")),
                    fps=_coerce_float(raw.get("fps")),
                    video_codec=video_codec,
                    audio_codec=audio_codec,
                    video_bitrate_kbps=_coerce_float(raw.get("vbr")) or _estimate_video_bitrate_kbps(raw),
                    audio_bitrate_kbps=_coerce_float(raw.get("abr")),
                    file_size_bytes=_coerce_int(raw.get("filesize")) or _coerce_int(raw.get("filesize_approx")),
                )
            )
    requires_auth = platform == "x"
    return ResolvedMedia(
        platform=platform,
        url=url,
        display_id=_coerce_string(info.get("display_id")) or _coerce_string(info.get("id")) or platform,
        title=_coerce_string(info.get("title")) or platform,
        uploader=_coerce_string(info.get("uploader")) or _coerce_string(info.get("channel")),
        duration_seconds=_coerce_float(info.get("duration")),
        thumbnail_url=_coerce_string(info.get("thumbnail")),
        webpage_url=_coerce_string(info.get("webpage_url")) or url,
        requires_auth=requires_auth,
        formats=formats,
        raw_info={
            "id": _coerce_string(info.get("id")),
            "extractor": _coerce_string(info.get("extractor")),
        },
    )


def _extract_info(
    request: ResolveRequest,
    url: str,
    *,
    download: bool,
) -> dict[str, object]:
    _require_yt_dlp()
    options = _build_ydl_options(
        request,
        output_dir=None,
        http_headers=None,
        download=download,
    )
    with YoutubeDL(options) as ydl:
        result = ydl.extract_info(url, download=download)
        if not isinstance(result, dict):
            raise ResolveError("yt-dlp did not return structured media info.")
        return result


def _build_ydl_options(
    request: ResolveRequest | DownloadRequest,
    *,
    output_dir: Path | None,
    http_headers: dict[str, str] | None,
    download: bool = True,
) -> dict[str, object]:
    opts: dict[str, object] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": not download,
        "paths": {"home": str(output_dir)} if output_dir else None,
        "outtmpl": str(output_dir / request.name_template) if output_dir and isinstance(request, DownloadRequest) else None,
        "writesubtitles": False,
        "writeautomaticsub": False,
        "writethumbnail": False,
        "writeinfojson": False,
        "restrictfilenames": False,
        "merge_output_format": "mp4",
        "format": _default_format_expression(request.selection_mode),
    }
    opts = {key: value for key, value in opts.items() if value is not None}

    if request.cookie_file:
        opts["cookiefile"] = str(Path(request.cookie_file).expanduser().resolve())
    if request.cookies_from_browser:
        opts["cookiesfrombrowser"] = request.cookies_from_browser
    if request.proxy:
        opts["proxy"] = request.proxy
    elif not request.use_env_proxy:
        opts["proxy"] = ""
    if http_headers:
        opts["http_headers"] = http_headers

    return opts


def _select_format(resolved: ResolvedMedia, request: DownloadRequest) -> FormatOption | None:
    if not resolved.formats:
        return None
    if request.format_id:
        for option in resolved.formats:
            if option.format_id == request.format_id:
                return option
        raise ValidationError("Requested format_id is not available for this media.")
    if resolved.platform == "missav" and request.quality:
        missav_options = [
            option for option in resolved.formats if option.height is not None and option.manifest_url
        ]
        if not missav_options:
            return None
        selected = select_quality_option(
            [
                type("MissavOption", (), {
                    "option_number": index + 1,
                    "label": option.quality_hint or "",
                    "height": int(option.height or 0),
                    "format_id": option.format_id,
                    "manifest_url": option.manifest_url,
                    "http_headers": option.http_headers,
                })()
                for index, option in enumerate(missav_options)
            ],
            request.quality,
        )
        for option in missav_options:
            if option.format_id == selected.format_id:
                return option
    return _pick_default_format(resolved.formats, request.selection_mode)


def _build_download_plan(
    resolved: ResolvedMedia,
    request: DownloadRequest,
    selected_format: FormatOption | None,
) -> DownloadPlan:
    if selected_format is not None:
        format_expression = _build_format_expression(request.selection_mode, selected_format)
        download_url = selected_format.manifest_url or request.url
        http_headers = selected_format.http_headers or None
        return DownloadPlan(
            selected_format=selected_format,
            format_expression=format_expression,
            download_url=download_url,
            http_headers=http_headers,
        )

    return DownloadPlan(
        selected_format=None,
        format_expression=_default_format_expression(request.selection_mode),
        download_url=request.url,
        http_headers=None,
    )


def _build_format_expression(selection_mode: SelectionMode, option: FormatOption) -> str:
    if selection_mode == "AUDIO_ONLY":
        if option.format_kind != "AUDIO_ONLY":
            raise ValidationError("AUDIO_ONLY downloads require an audio-only format_id.")
        return option.format_id

    if option.format_kind == "AUDIO_ONLY":
        raise ValidationError("Audio-only formats cannot be used for video downloads.")

    if selection_mode == "VIDEO_ONLY":
        return option.format_id
    if option.format_kind == "VIDEO_ONLY":
        return f"{option.format_id}+bestaudio/best"
    return option.format_id


def _default_format_expression(selection_mode: SelectionMode) -> str:
    if selection_mode == "AUDIO_ONLY":
        return "bestaudio/best"
    if selection_mode == "VIDEO_ONLY":
        return "bestvideo/best"
    return "bestvideo*+bestaudio/best"


def _pick_default_format(formats: list[FormatOption], selection_mode: SelectionMode) -> FormatOption | None:
    if selection_mode == "AUDIO_ONLY":
        audio_only_options = [option for option in formats if option.format_kind == "AUDIO_ONLY"]
        if audio_only_options:
            return max(audio_only_options, key=_format_sort_key)
        return None

    video_options = [option for option in formats if option.format_kind != "AUDIO_ONLY"]
    if not video_options:
        return None

    if selection_mode == "VIDEO_WITH_AUDIO":
        muxed_options = [option for option in video_options if option.format_kind == "MUXED"]
        if muxed_options:
            return max(muxed_options, key=_format_sort_key)
    return max(video_options, key=_format_sort_key)


def _load_cookie_rows(path: Path) -> list[tuple[str, str, str]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError as exc:
        raise CredentialError(f"Could not read cookie file: {path}") from exc

    rows: list[tuple[str, str, str]] = []
    for line in lines:
        if not line:
            continue
        if line.startswith("#HttpOnly_"):
            line = line.removeprefix("#HttpOnly_")
        elif line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        rows.append((parts[0], parts[5], parts[6]))
    return rows


def _mask_value(value: str) -> str:
    if len(value) <= 6:
        return value
    return f"{value[:3]}...{value[-3:]}"


def _validate_clip_args(request: DownloadRequest) -> None:
    if request.clip_end and request.clip_duration:
        raise ValidationError("--clip-end and --clip-duration cannot be used together")
    if any(value is not None for value in (request.clip_start, request.clip_end, request.clip_duration)):
        if shutil.which("ffmpeg") is None:
            raise DependencyError("ffmpeg is required for clipping but was not found in PATH")
    if request.clip_duration == "0":
        raise ValidationError("--clip-duration must be greater than 0")


def _resolve_output_filepath(info: dict[str, object]) -> str | None:
    filepath = _coerce_string(info.get("filepath"))
    if filepath:
        return filepath
    downloads = info.get("requested_downloads")
    if isinstance(downloads, list):
        for item in downloads:
            if isinstance(item, dict):
                value = _coerce_string(item.get("filepath"))
                if value:
                    return value
    return None


def _clip_media(input_path: Path, request: DownloadRequest) -> Path:
    output_path = _build_clip_output_path(input_path, request)
    command = ["ffmpeg", "-y", "-i", str(input_path)]

    if request.clip_start:
        command.extend(["-ss", request.clip_start])
    if request.clip_end:
        command.extend(["-to", request.clip_end])
    if request.clip_duration:
        command.extend(["-t", request.clip_duration])

    if request.selection_mode == "AUDIO_ONLY":
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

    if not request.keep_original:
        input_path.unlink(missing_ok=True)
    return output_path


def _build_clip_output_path(input_path: Path, request: DownloadRequest) -> Path:
    start = request.clip_start or "0"
    end_part = f"end-{request.clip_end}" if request.clip_end else ""
    dur_part = f"dur-{request.clip_duration}" if request.clip_duration else ""
    parts = [part for part in [f"start-{start}", end_part, dur_part] if part]
    suffix = ".".join(parts).replace(":", "-")
    extension = ".m4a" if request.selection_mode == "AUDIO_ONLY" else ".mp4"
    return input_path.with_name(f"{input_path.stem}.clip.{suffix}{extension}")


def _guess_mime_type(suffix: str, *, has_video: bool | None, has_audio: bool | None) -> str | None:
    lowered = suffix.lower()
    if lowered in {".mp4", ".m4v"}:
        if has_video is False and has_audio:
            return "audio/mp4"
        return "video/mp4"
    if lowered in {".m4a", ".aac"}:
        return "audio/mp4"
    if lowered == ".webm":
        if has_video is False and has_audio:
            return "audio/webm"
        return "video/webm"
    return None


def _probe_media(file_path: Path) -> dict[str, object]:
    if shutil.which("ffprobe") is None:
        raise DependencyError("ffprobe is required to inspect downloaded media but was not found in PATH")

    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(file_path),
    ]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else str(exc)
        raise DownloadFailure(f"ffprobe inspection failed: {stderr}") from exc

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise DownloadFailure("ffprobe inspection returned invalid JSON.") from exc

    streams = payload.get("streams")
    format_info = payload.get("format")
    if not isinstance(streams, list):
        streams = []
    if not isinstance(format_info, dict):
        format_info = {}

    video_stream = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "video"
        ),
        None,
    )
    audio_stream = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "audio"
        ),
        None,
    )

    size_bytes = file_path.stat().st_size if file_path.exists() else None
    format_size = _coerce_int(format_info.get("size"))
    return {
        "has_video": video_stream is not None,
        "has_audio": audio_stream is not None,
        "video_codec": _coerce_string(video_stream.get("codec_name")) if video_stream else None,
        "audio_codec": _coerce_string(audio_stream.get("codec_name")) if audio_stream else None,
        "width": _coerce_int(video_stream.get("width")) if video_stream else None,
        "height": _coerce_int(video_stream.get("height")) if video_stream else None,
        "fps": _parse_frame_rate(video_stream.get("avg_frame_rate")) if video_stream else None,
        "duration_seconds": _coerce_float(format_info.get("duration")),
        "size_bytes": format_size or size_bytes,
    }


def _detect_format_kind(
    *,
    video_codec: str | None,
    audio_codec: str | None,
    width: int | None,
    height: int | None,
) -> str:
    has_video = bool(video_codec) or width is not None or height is not None
    has_audio = bool(audio_codec)
    if has_video and has_audio:
        return "MUXED"
    if has_video:
        return "VIDEO_ONLY"
    if has_audio:
        return "AUDIO_ONLY"
    return "MUXED"


def _normalize_codec(value: str | None) -> str | None:
    if value == "none":
        return None
    return value


def _estimate_video_bitrate_kbps(raw: dict[str, object]) -> float | None:
    total_bitrate = _coerce_float(raw.get("tbr"))
    audio_bitrate = _coerce_float(raw.get("abr"))
    if total_bitrate is None:
        return None
    if audio_bitrate is None:
        return total_bitrate
    return max(total_bitrate - audio_bitrate, 0.0)


def _format_sort_key(option: FormatOption) -> tuple[float, float, float, float]:
    return (
        float(option.height or 0),
        float(option.fps or 0),
        float(option.video_bitrate_kbps or 0),
        float(option.audio_bitrate_kbps or 0),
    )


def _parse_frame_rate(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str) or not value or value == "0/0":
        return None
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        try:
            denominator_value = float(denominator)
            if denominator_value == 0:
                return None
            return float(numerator) / denominator_value
        except ValueError:
            return None
    try:
        return float(value)
    except ValueError:
        return None


def _require_yt_dlp() -> None:
    if YoutubeDL is None:
        raise DependencyError("yt-dlp is required but is not installed in the active Python environment")


def _coerce_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _coerce_int(value: object) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _coerce_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
