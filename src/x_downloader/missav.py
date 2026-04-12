from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import websocket


MISSAV_HOSTS = {"missav.ws", "www.missav.ws"}
CHROME_COMMON_ARGS = (
    "--no-first-run",
    "--no-default-browser-check",
    "--remote-allow-origins=*",
    "--disable-background-networking",
    "--disable-breakpad",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-features=Translate,OptimizationHints,CalculateNativeWinOcclusion",
    "--disable-sync",
    "--metrics-recording-only",
    "--password-store=basic",
    "--use-mock-keychain",
    "--window-size=1280,900",
)
MISSAV_RESOLVE_TIMEOUT_SECONDS = 45.0
MISSAV_POLL_INTERVAL_SECONDS = 1.0


class MissavResolverError(RuntimeError):
    """Raised when the MissAV browser fallback cannot resolve a playable stream."""


@dataclass(frozen=True)
class MissavVideoSource:
    manifest_url: str
    page_url: str
    http_headers: dict[str, str]
    user_agent: str
    page_title: str
    display_id: str


@dataclass(frozen=True)
class MissavQualityOption:
    option_number: int
    label: str
    height: int
    format_id: str
    manifest_url: str
    http_headers: dict[str, str]


def is_missav_url(url: str) -> bool:
    return urllib.parse.urlparse(url).netloc.lower() in MISSAV_HOSTS


def should_use_browser_fallback(error_message: str) -> bool:
    lowered = error_message.lower()
    return (
        "cloudflare anti-bot challenge" in lowered
        or ("http error 403" in lowered and "missav" in lowered)
        or ("http error 403" in lowered and "generic" in lowered)
        or "just a moment" in lowered
    )


def extract_stream_urls_from_scripts(script_text: str) -> dict[str, str]:
    packed_payload = _unpack_first_eval_payload(script_text)
    if not packed_payload:
        packed_payload = script_text

    result: dict[str, str] = {}
    for match in re.finditer(r"\b(source(?:842|1280)?)\s*=\s*['\"](https://[^'\"]+?\.m3u8)['\"]", packed_payload):
        result[match.group(1)] = match.group(2)
    return result


def choose_manifest_url(urls: list[str]) -> str | None:
    filtered_urls = [url for url in urls if url]
    if not filtered_urls:
        return None
    for url in filtered_urls:
        if url.endswith("/playlist.m3u8"):
            return url
    return filtered_urls[0]


def resolve_video_source(
    page_url: str,
    *,
    proxy: str | None = None,
    use_env_proxy: bool = False,
    chrome_profile: str | None = None,
    timeout_seconds: float = MISSAV_RESOLVE_TIMEOUT_SECONDS,
) -> MissavVideoSource:
    chrome_binary = find_chrome_binary()
    if chrome_binary is None:
        raise MissavResolverError("Chrome was not found on this machine, so MissAV browser fallback cannot start.")

    with _ChromeDebugSession(
        chrome_binary=chrome_binary,
        proxy=proxy,
        use_env_proxy=use_env_proxy,
        chrome_profile=chrome_profile,
        timeout_seconds=timeout_seconds,
    ) as chrome:
        chrome.open(page_url)

        scripts_text: str | None = None
        clicked_play = False
        deadline = time.monotonic() + timeout_seconds

        while time.monotonic() < deadline:
            state = chrome.get_page_state()

            manifest_url = choose_manifest_url(
                [state.get("hls_url"), *state.get("resource_urls", [])]
            )
            if manifest_url:
                return build_video_source(
                    page_url,
                    manifest_url,
                    state.get("user_agent") or "",
                    state.get("title") or "",
                )

            if not state.get("challenge_active") and state.get("ready_state") == "complete":
                if scripts_text is None:
                    scripts_text = chrome.get_scripts_text()
                    script_urls = extract_stream_urls_from_scripts(scripts_text)
                    manifest_url = choose_manifest_url(list(script_urls.values()))
                    if manifest_url:
                        return build_video_source(
                            page_url,
                            manifest_url,
                            state.get("user_agent") or "",
                            state.get("title") or "",
                        )

                if state.get("play_button_present") and not clicked_play:
                    chrome.click_play_button()
                    clicked_play = True

            time.sleep(MISSAV_POLL_INTERVAL_SECONDS)

    raise MissavResolverError(
        "Chrome opened the MissAV page but no playable HLS stream URL was discovered before timeout."
    )


def build_video_source(page_url: str, manifest_url: str, user_agent: str, page_title: str) -> MissavVideoSource:
    headers = {"Referer": page_url}
    if user_agent:
        headers["User-Agent"] = user_agent
    display_id = Path(urllib.parse.urlparse(page_url).path.strip("/")).name or "missav"
    return MissavVideoSource(
        manifest_url=manifest_url,
        page_url=page_url,
        http_headers=headers,
        user_agent=user_agent,
        page_title=page_title,
        display_id=display_id,
    )


def extract_manifest_formats(
    video_source: MissavVideoSource,
    *,
    proxy: str | None = None,
    use_env_proxy: bool = False,
) -> list[MissavQualityOption]:
    import yt_dlp

    options: dict[str, object] = {
        "skip_download": True,
        "quiet": True,
        "http_headers": video_source.http_headers,
    }
    if proxy:
        options["proxy"] = proxy
    elif not use_env_proxy:
        options["proxy"] = ""

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(video_source.manifest_url, download=False)

    formats = info.get("formats") or []
    quality_options = build_quality_options(formats, video_source.http_headers)
    if not quality_options:
        raise MissavResolverError("MissAV resolved an HLS manifest, but no selectable video formats were exposed.")
    return quality_options


def build_quality_options(formats: list[dict], default_headers: dict[str, str]) -> list[MissavQualityOption]:
    deduped: dict[tuple[int, str], MissavQualityOption] = {}
    for fmt in formats:
        height = fmt.get("height")
        manifest_url = fmt.get("url")
        format_id = fmt.get("format_id")
        if not isinstance(height, int) or not manifest_url or not format_id:
            continue
        headers = dict(default_headers)
        headers.update(fmt.get("http_headers") or {})
        deduped[(height, manifest_url)] = MissavQualityOption(
            option_number=0,
            label="",
            height=height,
            format_id=str(format_id),
            manifest_url=str(manifest_url),
            http_headers=headers,
        )

    ordered = sorted(deduped.values(), key=lambda item: item.height)
    label_map = _build_quality_label_map(len(ordered))

    results: list[MissavQualityOption] = []
    for index, option in enumerate(ordered, start=1):
        label = label_map.get(index - 1, "")
        results.append(
            MissavQualityOption(
                option_number=index,
                label=label,
                height=option.height,
                format_id=option.format_id,
                manifest_url=option.manifest_url,
                http_headers=option.http_headers,
            )
        )
    return results


def select_quality_option(options: list[MissavQualityOption], quality: str) -> MissavQualityOption:
    if not options:
        raise MissavResolverError("No MissAV formats are available to select from.")
    return options[_quality_index_for_choice(len(options), quality)]


def prompt_for_quality_choice(
    options: list[MissavQualityOption],
    *,
    input_func: Callable[[str], str] = input,
    output = None,
) -> MissavQualityOption:
    if not options:
        raise MissavResolverError("No MissAV formats are available to choose from.")
    if output is None:
        output = sys.stderr

    print("MissAV supports the following resolutions:", file=output)
    for option in options:
        alias = f" ({option.label})" if option.label else ""
        print(f"  {option.option_number}. {option.height}p{alias}", file=output)

    while True:
        choice = input_func(f"Select a resolution [1-{len(options)}]: ").strip()
        if choice.isdigit():
            index = int(choice)
            for option in options:
                if option.option_number == index:
                    return option
        print("Invalid selection. Please enter one of the listed numbers.", file=output)


def build_noninteractive_quality_error(options: list[MissavQualityOption]) -> str:
    listed = ", ".join(f"{option.height}p" for option in options)
    return (
        "MissAV supports multiple resolutions for this video "
        f"({listed}). Re-run with --quality low|medium|high in non-interactive mode."
    )


def find_chrome_binary() -> str | None:
    system = os.name
    candidates: list[Path] = []

    if system == "nt":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        candidates.extend(
            [
                Path(program_files) / "Google/Chrome/Application/chrome.exe",
                Path(program_files_x86) / "Google/Chrome/Application/chrome.exe",
                Path(local_app_data) / "Google/Chrome/Application/chrome.exe",
            ]
        )
    else:
        candidates.extend(
            [
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                Path("/usr/bin/google-chrome"),
                Path("/usr/bin/google-chrome-stable"),
                Path("/snap/bin/chromium"),
            ]
        )

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    found = shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    return found


def get_chrome_user_data_root() -> Path:
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "Google/Chrome/User Data"
        return Path.home() / "AppData/Local/Google/Chrome/User Data"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Google/Chrome"
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home) / "google-chrome"
    return Path.home() / ".config/google-chrome"


def _unpack_first_eval_payload(script_text: str) -> str | None:
    match = re.search(
        r"eval\(function\(p,a,c,k,e,d\)\{.*?\}\('(?P<payload>(?:\\.|[^'])*)',(?P<base>\d+),(?P<count>\d+),'(?P<words>(?:\\.|[^'])*)'\.split\('\|'\),0,\{\}\)\)",
        script_text,
        flags=re.DOTALL,
    )
    if not match:
        return None

    payload = bytes(match.group("payload"), "utf-8").decode("unicode_escape")
    base = int(match.group("base"))
    count = int(match.group("count"))
    words = bytes(match.group("words"), "utf-8").decode("unicode_escape").split("|")
    if len(words) < count:
        return None

    unpacked = payload
    for index in range(count - 1, -1, -1):
        token = _to_base(index, base)
        replacement = words[index]
        if not replacement:
            continue
        unpacked = re.sub(rf"\b{re.escape(token)}\b", replacement, unpacked)
    return unpacked


def _to_base(number: int, base: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    if number == 0:
        return "0"
    chars: list[str] = []
    current = number
    while current:
        current, remainder = divmod(current, base)
        chars.append(alphabet[remainder])
    return "".join(reversed(chars))


class _ChromeDebugSession:
    def __init__(
        self,
        *,
        chrome_binary: str,
        proxy: str | None,
        use_env_proxy: bool,
        chrome_profile: str | None,
        timeout_seconds: float,
    ) -> None:
        self._chrome_binary = chrome_binary
        self._proxy = proxy
        self._use_env_proxy = use_env_proxy
        self._chrome_profile = chrome_profile
        self._timeout_seconds = timeout_seconds
        self._profile_dir = Path(tempfile.mkdtemp(prefix="xdl-missav-chrome-"))
        self._port = self._reserve_port()
        self._process: subprocess.Popen[str] | None = None
        self._browser_socket: websocket.WebSocket | None = None
        self._browser_message_id = 0
        self._session_id: str | None = None
        self._target_id: str | None = None

    def __enter__(self) -> "_ChromeDebugSession":
        self._launch()
        browser_ws_url = self._wait_for_devtools()
        self._browser_socket = websocket.create_connection(browser_ws_url, timeout=self._timeout_seconds)
        self._target_id, self._session_id = self._create_page_session()
        self._call_session("Page.enable")
        self._call_session("Runtime.enable")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._browser_socket is not None:
            try:
                if self._target_id:
                    self._call_browser("Target.closeTarget", {"targetId": self._target_id})
            except Exception:
                pass
            try:
                self._browser_socket.close()
            except Exception:
                pass

        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()

        shutil.rmtree(self._profile_dir, ignore_errors=True)

    def open(self, url: str) -> None:
        self._call_session("Page.navigate", {"url": url})

    def get_page_state(self) -> dict:
        return self._evaluate(
            """
            (() => {
                const bodyText = document.body ? document.body.innerText : '';
                return {
                    title: document.title,
                    ready_state: document.readyState,
                    challenge_active: document.title.includes('Just a moment')
                        || document.title.includes('请稍候')
                        || bodyText.includes('正在进行安全验证')
                        || bodyText.includes('Verifying you are human'),
                    hls_url: window.hls?.url || null,
                    user_agent: navigator.userAgent,
                    resource_urls: performance
                        .getEntriesByType('resource')
                        .map(entry => entry.name)
                        .filter(name => /\\.m3u8(?:$|\\?)/.test(name))
                        .slice(-20),
                    play_button_present: !!document.querySelector('[data-plyr="play"]'),
                };
            })()
            """
        )

    def get_scripts_text(self) -> str:
        return self._evaluate(
            """
            (() => Array.from(document.scripts).map(script => script.textContent || '').join('\\n'))()
            """
        )

    def click_play_button(self) -> None:
        self._evaluate(
            """
            (() => {
                const button = document.querySelector('[data-plyr="play"]');
                if (button) {
                    button.click();
                    return true;
                }
                return false;
            })()
            """
        )

    def _evaluate(self, expression: str):
        result = self._call_session(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        evaluation = result.get("result", {})
        if "value" in evaluation:
            return evaluation["value"]
        raise MissavResolverError(f"Chrome runtime evaluation did not return a value: {evaluation}")

    def _launch(self) -> None:
        self._prepare_profile_dir()
        args = [
            self._chrome_binary,
            *CHROME_COMMON_ARGS,
            f"--remote-debugging-port={self._port}",
            f"--user-data-dir={self._profile_dir}",
            "about:blank",
        ]
        if self._chrome_profile:
            args.append(f"--profile-directory={self._chrome_profile}")
        if self._proxy:
            args.append(f"--proxy-server={self._proxy}")
        elif not self._use_env_proxy:
            args.append("--no-proxy-server")

        self._process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            text=True,
        )

    def _prepare_profile_dir(self) -> None:
        if not self._chrome_profile:
            return

        chrome_root = get_chrome_user_data_root()
        source_profile_dir = chrome_root / self._chrome_profile
        if not source_profile_dir.exists():
            raise MissavResolverError(
                f"Chrome profile '{self._chrome_profile}' was not found under {chrome_root}."
            )

        local_state = chrome_root / "Local State"
        if local_state.exists():
            _safe_copy2(local_state, self._profile_dir / "Local State")

        shutil.copytree(
            source_profile_dir,
            self._profile_dir / self._chrome_profile,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(
                "Cache",
                "Code Cache",
                "GPUCache",
                "GrShaderCache",
                "GraphiteDawnCache",
                "DawnCache",
                "Crashpad",
                "Service Worker\\CacheStorage",
                "Media Cache",
                "VideoDecodeStats",
            ),
            copy_function=_safe_copy2,
        )

    def _wait_for_devtools(self) -> str:
        deadline = time.monotonic() + self._timeout_seconds
        version_url = f"http://127.0.0.1:{self._port}/json/version"
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(version_url, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    return payload["webSocketDebuggerUrl"]
            except (KeyError, OSError, urllib.error.URLError, json.JSONDecodeError):
                time.sleep(0.2)
        raise MissavResolverError("Chrome started, but the DevTools endpoint never became ready.")

    def _create_page_session(self) -> tuple[str, str]:
        target_id = self._call_browser("Target.createTarget", {"url": "about:blank"})["targetId"]
        session_id = self._call_browser(
            "Target.attachToTarget",
            {"targetId": target_id, "flatten": True},
        )["sessionId"]
        return target_id, session_id

    def _call_browser(self, method: str, params: dict | None = None) -> dict:
        return self._send_command(method=method, params=params, session_id=None)

    def _call_session(self, method: str, params: dict | None = None) -> dict:
        if not self._session_id:
            raise MissavResolverError("Chrome DevTools session has not been attached.")
        return self._send_command(method=method, params=params, session_id=self._session_id)

    def _send_command(self, *, method: str, params: dict | None, session_id: str | None) -> dict:
        if self._browser_socket is None:
            raise MissavResolverError("Chrome DevTools browser socket is not connected.")

        self._browser_message_id += 1
        message_id = self._browser_message_id
        payload: dict[str, object] = {"id": message_id, "method": method}
        if params:
            payload["params"] = params
        if session_id:
            payload["sessionId"] = session_id

        self._browser_socket.send(json.dumps(payload))

        while True:
            raw = self._browser_socket.recv()
            response = json.loads(raw)
            if response.get("id") != message_id:
                continue
            if "error" in response:
                raise MissavResolverError(f"Chrome DevTools command failed for {method}: {response['error']}")
            return response.get("result", {})

    @staticmethod
    def _reserve_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])


def _build_quality_label_map(count: int) -> dict[int, str]:
    if count <= 0:
        return {}
    if count == 1:
        return {0: "high"}
    labels = {0: "low", count - 1: "high"}
    if count >= 3:
        labels[count // 2] = "medium"
    return labels


def _quality_index_for_choice(count: int, quality: str) -> int:
    if count <= 1:
        return 0
    if quality == "low":
        return 0
    if quality == "high":
        return count - 1
    if quality == "medium":
        return count // 2
    raise MissavResolverError("Unsupported MissAV quality selection.")


def _safe_copy2(src: str | Path, dst: str | Path) -> str:
    try:
        return shutil.copy2(src, dst)
    except PermissionError:
        return str(dst)
