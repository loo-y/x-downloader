from __future__ import annotations

import json
import sys
from dataclasses import asdict

from .api import download_media, resolve_media, validate_credential
from .errors import XDownloaderError
from .types import DownloadRequest, ResolveRequest


def _emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        raise SystemExit(2)

    payload = json.loads(raw)
    operation = payload.get("operation")
    try:
        if operation == "resolve":
            request = ResolveRequest(**payload["request"])
            resolved = resolve_media(request)
            _emit({"event": "metadata", "data": asdict(resolved)})
            return
        if operation == "validate_credential":
            request = payload["request"]
            result = validate_credential(request["platform"], request["cookie_file"])
            _emit({"event": "completed", "data": asdict(result)})
            return
        if operation == "download":
            request = DownloadRequest(**payload["request"])

            def on_progress(progress) -> None:
                _emit({"event": "progress", "data": asdict(progress)})

            result = download_media(request, progress_hook=on_progress)
            _emit({"event": "completed", "data": asdict(result)})
            return
        raise XDownloaderError("UNKNOWN_OPERATION", f"Unsupported operation: {operation}")
    except XDownloaderError as exc:
        _emit(
            {
                "event": "error",
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                    "details": exc.details,
                },
            }
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
