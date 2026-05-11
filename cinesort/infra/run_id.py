from __future__ import annotations

import re
from typing import Optional
from uuid import uuid4


RUN_ID_PATTERN = re.compile(r"^\d{8}_\d{6}_\d{3}$")


def normalize_or_generate_run_id(existing: Optional[str]) -> str:
    """
    Preserve the current run_id format when provided, otherwise fallback to uuid4().hex.
    """
    candidate = str(existing or "").strip()
    if candidate and RUN_ID_PATTERN.match(candidate):
        return candidate
    return uuid4().hex
