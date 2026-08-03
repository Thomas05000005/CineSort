"""ARCH-08 (Vague M / M-07) — extraction de la classe ``RunState``.

Historiquement defini dans ``cinesort.ui.api.cinesort_api`` (L118-L282), ce
container etait melange avec 2700+ lignes de facade API. Cette extraction
isole la machinerie d'etat d'un run (scan + apply) dans un module dedie pour :

- reduire la taille de ``cinesort_api.py`` (-165 LOC environ),
- faciliter la testabilite unitaire (pas besoin de charger toute la facade),
- documenter clairement le contrat thread-safe (``self.lock`` +
  ``self._file_log_lock``).

L'import historique ``from cinesort.ui.api.cinesort_api import RunState`` reste
fonctionnel grace a un re-export dans ``cinesort_api.py`` (back-compat callers
pywebview JS / tests existants).

Note de design :
- Aucune dependance sur les autres ``*_support`` modules pour eviter les
  cycles d'import.
- ``_env_truthy`` est duplique localement (3 lignes triviales) plutot
  qu'importe depuis ``cinesort_api`` : importer la facade depuis ce module
  creerait un cycle (cinesort_api importe RunState).
"""

from __future__ import annotations

import os
import threading
import time
from typing import Dict, List, Optional, Tuple

import cinesort.domain.core as core
import cinesort.infra.state as state
from cinesort.app import JobRunner
from cinesort.infra.db import SQLiteStore

# Constante de garde pour eviter une croissance unbounded de ``self.logs``
# en memoire. Doit rester aligne avec celle de cinesort_api.py (qui la
# re-exporte pour back-compat module-level).
MAX_RUN_LOG_ITEMS = 5000


def _env_truthy(name: str) -> bool:
    """Petit helper local (cf cinesort_api._env_truthy) pour eviter le cycle
    d'import. Garde la meme semantique : reconnait 1/true/yes/on/debug."""
    v = str(os.environ.get(name, "")).strip().lower()
    return v in {"1", "true", "yes", "on", "debug"}


class RunState:
    def __init__(
        self,
        run_paths: state.RunPaths,
        cfg: core.Config,
        *,
        runner: JobRunner,
        store: SQLiteStore,
    ):
        self.paths = run_paths
        self.cfg = cfg
        self.runner = runner
        self.store = store
        self.lock = threading.Lock()
        # Fix audit 2026-05-25 (v1.5.3) Vague H : lock dedie au file append
        # ui_log.txt. Sans ce lock, les writes multi-thread produisaient des
        # lignes interleavees ([HH:MM:SS] partiel + autre ligne). On garde un
        # lock distinct de self.lock pour ne pas bloquer la mutation
        # in-memory pendant l'I/O fichier.
        self._file_log_lock = threading.Lock()
        self.running = False
        self.done = False
        self.error: Optional[str] = None

        self.idx = 0
        self.total = 0
        self.current_folder = ""
        self.started_ts = time.time()
        self.progress_samples: List[Tuple[float, int]] = []
        self.speed_ewma = 0.0

        self.logs: List[Dict[str, str]] = []  # {ts, level, msg}
        # F19 : index ABSOLU du 1er item encore conserve dans self.logs. Le trim
        # de retention (log(), plus bas) evince les plus anciens ; sans cet
        # offset, les index de pagination de get_status (absolus) et les index
        # de liste (relatifs) divergeaient -> next_log_index fige a
        # MAX_RUN_LOG_ITEMS et panneau logs gele a vie.
        self.logs_offset: int = 0
        self.rows: List[core.PlanRow] = []
        self.stats: Optional[core.Stats] = None

        # APPLY-2 (v1.5.4) : etat d'avancement de la phase apply (symetrique
        # au scan). Permet au frontend de poller run/status et d'afficher une
        # barre de progression realiste pendant l'application (rows/jellyfin/
        # plex/cleanup) au lieu d'un spinner aveugle.
        self.apply_running: bool = False
        self.apply_done: bool = False
        self.apply_phase: str = ""  # 'precheck'|'duplicates'|'rows'|'cleanup'|'jellyfin'|'plex'|'summary'
        self.apply_idx: int = 0
        self.apply_total: int = 0
        self.apply_current: str = ""
        self.apply_started_ts: float = 0.0
        self.apply_speed_ewma: float = 0.0
        self.apply_progress_samples: List[Tuple[float, int]] = []
        self.apply_dry_run: bool = False

    def log(self, level: str, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        item = {"ts": ts, "level": level, "msg": msg}
        with self.lock:
            self.logs.append(item)
            if len(self.logs) > MAX_RUN_LOG_ITEMS:
                # F19 : mutation EN PLACE + comptabilisation des items evinces,
                # pour que logs_offset + len(self.logs) reste l'index absolu du
                # prochain item a emettre (cf run_flow_support._get_status_impl).
                excess = len(self.logs) - MAX_RUN_LOG_ITEMS
                del self.logs[:excess]
                self.logs_offset += excess
        # best-effort UI log persistence
        # Fix audit 2026-05-25 (v1.5.3) Vague H : file append protege par
        # _file_log_lock pour eviter les lignes interleavees multi-thread.
        try:
            self.paths.ui_log_txt.parent.mkdir(parents=True, exist_ok=True)
            with self._file_log_lock, open(self.paths.ui_log_txt, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {level}: {msg}\n")
        # except Exception intentionnel : boundary top-level
        except Exception as exc:
            if _env_truthy("CINESORT_DEBUG"):
                try:
                    with (
                        self._file_log_lock,
                        open(self.paths.run_dir / "debug_runstate.log", "a", encoding="utf-8") as f,
                    ):
                        f.write(f"[{ts}] WARN ui_log write failed: {exc}\n")
                except (OSError, PermissionError):
                    return

    def progress(self, idx: int, total: int, current: str) -> None:
        now = time.time()
        with self.lock:
            prev_idx = self.idx
            prev_ts = self.progress_samples[-1][0] if self.progress_samples else self.started_ts

            self.idx = idx
            self.total = total
            self.current_folder = current

            if idx > prev_idx:
                dt = max(0.001, now - prev_ts)
                inst_speed = (idx - prev_idx) / dt
                # Exponential smoothing to avoid a noisy ETA.
                alpha = 0.28
                self.speed_ewma = (
                    inst_speed if self.speed_ewma <= 0.0 else (alpha * inst_speed + (1.0 - alpha) * self.speed_ewma)
                )
            elif self.speed_ewma <= 0.0 and idx > 0:
                elapsed = max(0.001, now - self.started_ts)
                self.speed_ewma = idx / elapsed

            self.progress_samples.append((now, idx))
            if len(self.progress_samples) > 400:
                self.progress_samples = self.progress_samples[-400:]

    # APPLY-2 (v1.5.4) : trois methodes symetriques au scan (progress) pour
    # piloter l'etat de la phase apply. Toutes mutations sont protegees par
    # self.lock pour rester thread-safe vis-a-vis du polling get_status.

    def apply_begin(self, total: int, dry_run: bool, phase: str = "rows") -> None:
        """Reset les compteurs apply et passe l'etat en running."""
        now = time.time()
        with self.lock:
            self.apply_running = True
            self.apply_done = False
            self.apply_phase = str(phase or "rows")
            self.apply_idx = 0
            self.apply_total = int(total or 0)
            self.apply_current = ""
            self.apply_started_ts = now
            self.apply_speed_ewma = 0.0
            self.apply_progress_samples = []
            self.apply_dry_run = bool(dry_run)

    def apply_progress(self, idx: int, total: int, current: str, phase: Optional[str] = None) -> None:
        """Avance le compteur d'application. Calque sur progress() L178-L202."""
        now = time.time()
        with self.lock:
            prev_idx = self.apply_idx
            prev_ts = (
                self.apply_progress_samples[-1][0] if self.apply_progress_samples else (self.apply_started_ts or now)
            )

            self.apply_idx = int(idx or 0)
            self.apply_total = int(total or 0)
            self.apply_current = str(current or "")
            if phase is not None:
                self.apply_phase = str(phase)

            if self.apply_idx > prev_idx:
                dt = max(0.001, now - prev_ts)
                inst_speed = (self.apply_idx - prev_idx) / dt
                alpha = 0.28
                self.apply_speed_ewma = (
                    inst_speed
                    if self.apply_speed_ewma <= 0.0
                    else (alpha * inst_speed + (1.0 - alpha) * self.apply_speed_ewma)
                )
            elif self.apply_speed_ewma <= 0.0 and self.apply_idx > 0:
                elapsed = max(0.001, now - (self.apply_started_ts or now))
                self.apply_speed_ewma = self.apply_idx / elapsed

            self.apply_progress_samples.append((now, self.apply_idx))
            if len(self.apply_progress_samples) > 400:
                self.apply_progress_samples = self.apply_progress_samples[-400:]

    def apply_end(self, error: Optional[str] = None) -> None:
        """Marque la fin de l'apply (succes ou erreur). Conserve idx/total
        pour l'affichage final cote frontend."""
        with self.lock:
            self.apply_running = False
            self.apply_done = True
            if error:
                # On ne surcharge pas self.error (champ scan) ; le frontend lit
                # apply.done + run.error si besoin. Garde une trace neanmoins.
                if not self.error:
                    self.error = str(error)


__all__ = ["RunState", "MAX_RUN_LOG_ITEMS"]
