"""Locate and load the JSON Schema for the config model."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping, Optional, Union

ENV_SCHEMA_PATH = "FWOS_SCHEMA_PATH"
ISO_SCHEMA_PATH = Path("/usr/lib/fwos/schema.json")
REPO_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config" / "schema.json"


class SchemaNotFoundError(FileNotFoundError):
    pass


def schema_path(explicit: Optional[Union[str, Path]] = None) -> Path:
    """Resolve the schema location: explicit argument, then $FWOS_SCHEMA_PATH,
    then the ISO install location, then the repository checkout."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get(ENV_SCHEMA_PATH)
    if env:
        candidates.append(Path(env))
    candidates.extend([ISO_SCHEMA_PATH, REPO_SCHEMA_PATH])
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SchemaNotFoundError(
        "config schema not found; looked at: "
        + ", ".join(str(c) for c in candidates)
    )


def load_schema(explicit: Optional[Union[str, Path]] = None) -> Mapping:
    with schema_path(explicit).open(encoding="utf-8") as handle:
        return json.load(handle)
