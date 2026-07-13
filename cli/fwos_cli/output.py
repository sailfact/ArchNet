"""Output formatting: human text or one stable JSON envelope on stdout.

The JSON shape is part of the automation contract:
    {"ok": bool, "action": str, "data": {...}, "errors": [{code, message, path}]}
"""

from __future__ import annotations

import json
import sys
from typing import Iterable, Mapping, Optional, Sequence


def emit(
    json_mode: bool,
    action: str,
    ok: bool,
    data: Optional[Mapping] = None,
    errors: Optional[Sequence[Mapping]] = None,
    human_lines: Optional[Iterable[str]] = None,
) -> None:
    if json_mode:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "action": action,
                    "data": dict(data or {}),
                    "errors": [dict(error) for error in (errors or [])],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    for line in human_lines or []:
        print(line)
    for error in errors or []:
        location = f" at {error['path']}" if error.get("path") else ""
        print(
            f"error [{error.get('code', 'error')}]{location}:"
            f" {error['message']}",
            file=sys.stderr,
        )
