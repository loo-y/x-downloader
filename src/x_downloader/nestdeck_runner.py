from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass

from .api import download_media, resolve_media, validate_credential
from .errors import XDownloaderError
from .types import DownloadRequest, ResolveRequest


def _emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _to_wire_payload(value: object) -> object:
    if is_dataclass(value):
        return _to_wire_payload(asdict(value))
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, item in value.items():
            result[key] = _to_wire_payload(item)
            camel_key = _to_camel_case(key)
            if camel_key != key:
                result[camel_key] = result[key]
        return result
    if isinstance(value, list):
        return [_to_wire_payload(item) for item in value]
    return value


def _to_camel_case(value: str) -> str:
    if "_" not in value:
        return value
    first, *rest = value.split("_")
    return first + "".join(part[:1].upper() + part[1:] for part in rest)


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
            _emit({"event": "metadata", "data": _to_wire_payload(resolved)})
            return
        if operation == "validate_credential":
            request = payload["request"]
            result = validate_credential(request["platform"], request["cookie_file"])
            _emit({"event": "completed", "data": _to_wire_payload(result)})
            return
        if operation == "download":
            request = DownloadRequest(**payload["request"])

            def on_progress(progress) -> None:
                _emit({"event": "progress", "data": _to_wire_payload(progress)})

            result = download_media(request, progress_hook=on_progress)
            _emit({"event": "completed", "data": _to_wire_payload(result)})
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
