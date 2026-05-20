from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    # V8-01 spec 08 Traitement : etats supplementaires pour Run Control.
    # Cf docs/internal/design/refonte_2026_05_17/screens/08-traitement.md §5
    PAUSED = "PAUSED"
    SAVED = "SAVED"
    AWAITING_VALIDATION = "AWAITING_VALIDATION"


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    status: RunStatus
    created_ts: float
    started_ts: Optional[float]
    ended_ts: Optional[float]
    cancel_requested: bool
    running: bool
    done: bool
    error: Optional[str]
