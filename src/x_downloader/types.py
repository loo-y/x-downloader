from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


PlatformKey = Literal["x", "youtube", "missav"]
CredentialState = Literal["valid", "invalid", "unsupported"]


@dataclass(frozen=True)
class ResolveRequest:
    url: str
    cookie_file: str | None = None
    proxy: str | None = None
    use_env_proxy: bool = False
    cookies_from_browser: tuple[str, ...] | None = None
    chrome_profile: str | None = None
    chrome_binary: str | None = None


@dataclass(frozen=True)
class FormatOption:
    format_id: str
    label: str
    ext: str | None
    protocol: str | None
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None
    filesize: int | None
    manifest_url: str | None = None
    http_headers: dict[str, str] = field(default_factory=dict)
    quality_hint: str | None = None


@dataclass(frozen=True)
class ResolvedMedia:
    platform: PlatformKey
    url: str
    display_id: str
    title: str
    uploader: str | None
    duration_seconds: float | None
    thumbnail_url: str | None
    webpage_url: str | None
    requires_auth: bool
    formats: list[FormatOption]
    raw_info: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DownloadRequest:
    url: str
    output_dir: str
    format_id: str | None = None
    cookie_file: str | None = None
    proxy: str | None = None
    use_env_proxy: bool = False
    cookies_from_browser: tuple[str, ...] | None = None
    chrome_profile: str | None = None
    chrome_binary: str | None = None
    audio_only: bool = False
    quality: Literal["low", "medium", "high"] | None = None
    name_template: str = "%(uploader)s-%(id)s-%(title).80B.%(ext)s"
    clip_start: str | None = None
    clip_end: str | None = None
    clip_duration: str | None = None
    keep_original: bool = False


@dataclass(frozen=True)
class DownloadResult:
    platform: PlatformKey
    file_path: str
    title: str
    display_id: str
    mime_type: str | None
    ext: str | None
    size_bytes: int | None
    info: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CredentialCheck:
    platform: PlatformKey
    state: CredentialState
    message: str
    account_hint: str | None
    checked_fields: list[str]


@dataclass(frozen=True)
class DownloadProgress:
    phase: Literal["resolving", "downloading", "postprocessing", "finished"]
    downloaded_bytes: int | None
    total_bytes: int | None
    speed_bytes_per_second: float | None
    eta_seconds: float | None
    percent: float | None
    filename: str | None


def ensure_directory(path_value: str) -> Path:
    path = Path(path_value).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path
