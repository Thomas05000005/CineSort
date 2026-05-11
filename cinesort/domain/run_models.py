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
