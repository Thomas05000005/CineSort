from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final, Optional

# Spec 08 §3.5 : duree pendant laquelle un apply reste annulable.
#
# Issue #491 : cette valeur etait ecrite DEUX fois, dans `ui/api/apply_support`
# (qui refuse l'undo avec un HTTP 410 passe le delai) et dans
# `ui/api/dashboard_support` (qui envoie le compte a rebours a l'interface).
# Les deux commentaires disaient « en miroir de l'autre », mais rien ne
# l'imposait : changer la politique d'un seul cote donnait une UI qui annonce
# « encore 3 h » face a un backend qui refuse deja, ou l'inverse. La valeur
# appartient a la politique de run, donc au domaine ; les deux modules `ui`
# la lisent ici (`ui -> domain` est autorise par les contrats d'architecture).
UNDO_DEADLINE_SECONDS: Final[int] = 24 * 3600


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
