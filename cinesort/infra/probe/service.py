from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from cinesort.domain.probe_models import NormalizedProbe
from cinesort.infra.db import SQLiteStore

from ._source_circuit_breaker import (
    SourceCircuitBreaker,
    SourceDegradedError,
    extract_network_source,
    get_default_breaker,
)
from .adaptive_timeout import (
    AdaptiveTimeoutConfig,
    compute_adaptive_timeout,
    resolve_adaptive_timeout_config,
)
from .constants import FILE_PROBE_TIMEOUT_S, PROBE_WORKERS_AUTO_CAP, PROBE_WORKERS_MAX
from .disk_cache import get_disk_cache, upsert_disk_cache
from .ffprobe_backend import run_ffprobe_json
from .mediainfo_backend import run_mediainfo_json
from .normalize import normalize_probe
from .tooling import RunnerFn, ToolStatus, WhichFn, default_runner, get_tools_status

logger = logging.getLogger(__name__)


def _normalize_backend(value: Any) -> str:
    v = str(value or "auto").strip().lower()
    if v not in {"auto", "mediainfo", "ffprobe", "none"}:
        return "auto"
    return v


def _resolve_probe_workers(value: Any) -> int:
    """Normalise `probe_workers` : 0 = auto (cpu_count cape a 8), borne [1, 16].

    V5-04 (Polish Total v7.7.0, R5-STRESS-1).
    """
    try:
        n = int(value) if value is not None else 0
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        cpu = os.cpu_count() or 4
        n = min(cpu, PROBE_WORKERS_AUTO_CAP)
    return max(1, min(PROBE_WORKERS_MAX, n))


def _normalize_probe_settings(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw = settings if isinstance(settings, dict) else {}
    # M1 : timeout configurable depuis les settings, avec bornes 5s-300s.
    # Si absent, fallback sur FILE_PROBE_TIMEOUT_S (30s) defini dans constants.
    timeout_raw = raw.get("probe_timeout_s")
    try:
        timeout = float(timeout_raw) if timeout_raw is not None else None
    except (TypeError, ValueError):
        timeout = None
    if timeout is None or timeout <= 0:
        timeout = float(FILE_PROBE_TIMEOUT_S)
    timeout = max(5.0, min(300.0, timeout))
    # V5-04 : parallelisation probe batch — opt-in via settings.
    parallelism_raw = raw.get("probe_parallelism_enabled")
    if parallelism_raw is None:
        parallelism_enabled = True
    else:
        parallelism_enabled = bool(parallelism_raw)
    workers = _resolve_probe_workers(raw.get("probe_workers"))
    return {
        "probe_backend": _normalize_backend(raw.get("probe_backend")),
        "mediainfo_path": str(raw.get("mediainfo_path") or "").strip(),
        "ffprobe_path": str(raw.get("ffprobe_path") or "").strip(),
        "probe_timeout_s": timeout,
        "probe_parallelism_enabled": parallelism_enabled,
        "probe_workers": workers,
    }


class ProbeService:
    def __init__(
        self,
        store: SQLiteStore,
        *,
        runner: RunnerFn = default_runner,
        which_fn: Optional[WhichFn] = None,
        source_breaker: Optional[SourceCircuitBreaker] = None,
    ) -> None:
        self.store = store
        self.runner = runner
        if which_fn is None:
            from shutil import which as default_which

            self.which_fn = default_which
        else:
            self.which_fn = which_fn
        # PERF-1 (Phase 2 v7.8.0) : cache `get_tools_status` par signature
        # (mediainfo_path, ffprobe_path). Avant ce cache, chaque probe_file
        # lance 2 subprocess `--version` (~30-80ms x2 sur Windows). Sur
        # 5000 films premier scan = ~500s perdues. Cache invalide par
        # changement de signature (cf invalidate_tools_status_cache).
        self._tools_status_cache: Optional[Dict[str, Any]] = None
        self._tools_status_cache_sig: str = ""
        # Iter13 CIRCUIT_BREAKER : breaker par source UNC (defaut singleton
        # process). Permet d'isoler un partage reseau en panne sans casser
        # les probes des autres sources (disque local, autre NAS).
        # Cf cinesort/infra/probe/_source_circuit_breaker.py.
        self._source_breaker: SourceCircuitBreaker = (
            source_breaker if source_breaker is not None else get_default_breaker()
        )

    def invalidate_tools_status_cache(self) -> None:
        """Force le prochain appel a get_tools_status() a recharger les binaires.

        A appeler depuis save_settings() apres changement des paths probe.
        Idempotent : peut etre appele a vide sans effet.
        """
        self._tools_status_cache = None
        self._tools_status_cache_sig = ""

    def _get_tools_cached(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Variante cachee de la fonction module get_tools_status().

        Retourne le dict ToolStatus indexes par nom (cf appel ligne 145).
        Cache lookup par (mediainfo_path, ffprobe_path) — si l'un change,
        on relance les 2 subprocess pour rester coherent.
        """
        sig = f"{cfg.get('mediainfo_path', '')}|{cfg.get('ffprobe_path', '')}"
        if self._tools_status_cache is not None and self._tools_status_cache_sig == sig:
            return self._tools_status_cache
        tools = get_tools_status(
            mediainfo_path=cfg["mediainfo_path"],
            ffprobe_path=cfg["ffprobe_path"],
            runner=self.runner,
            which_fn=self.which_fn,
        )
        self._tools_status_cache = tools
        self._tools_status_cache_sig = sig
        return tools

    def get_tools_status(self, settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = _normalize_probe_settings(settings)
        tools = self._get_tools_cached(cfg)
        return {
            "probe_backend": cfg["probe_backend"],
            "tools": {k: v.to_dict() for k, v in tools.items()},
        }

    def _is_tool_unavailable_failure(
        self,
        *,
        backend: str,
        raw_mediainfo: Optional[Dict[str, Any]],
        raw_ffprobe: Optional[Dict[str, Any]],
        mediainfo_tool: ToolStatus,
        ffprobe_tool: ToolStatus,
    ) -> bool:
        """Fix audit 2026-05-25 (v1.5.5) Vague K (FIX 4) : detection 'tool unavailable'.

        Retourne True ssi le probe a echoue PARCE QUE le tool n'est pas dispo
        (path obsolete, binaire absent du PATH). Cas detectes :
        - backend=mediainfo + mediainfo_tool.available=False
        - backend=ffprobe + ffprobe_tool.available=False
        - backend=auto + AUCUN tool dispo (les 2 KO, sinon on a au moins une probe)
        - backend != none + raw_mediainfo et raw_ffprobe sont tous deux None
          alors qu'au moins un tool est dispo (signifie subprocess WinError 2)

        Cf scenario typique : settings.json garde un ancien path
        "C:\\Users\\.cinesort_tools\\ffprobe\\ffprobe.exe" qui n'existe plus,
        which_fn ne lance pas (explicit consume), subprocess leve OSError.
        """
        if backend == "none":
            return False
        if backend == "mediainfo":
            return not mediainfo_tool.available
        if backend == "ffprobe":
            return not ffprobe_tool.available
        # backend == "auto"
        if not mediainfo_tool.available and not ffprobe_tool.available:
            return True
        # Edge case : tool dispo selon detection, mais les 2 runs ont echoue
        # (probable WinError 2 -> path en cache invalide entre 2 boots).
        return raw_mediainfo is None and raw_ffprobe is None

    def _is_tool_definitely_unavailable(
        self,
        *,
        backend: str,
        mediainfo_tool: ToolStatus,
        ffprobe_tool: ToolStatus,
    ) -> bool:
        """AUDIT 2026-06-11 (R3e, gap[4]) : variante STRICTE pour le circuit breaker.

        Ne classe 'tool unavailable' QUE les cas non ambigus ou le binaire est
        reellement absent (detection available=False). Le cas auto + binaires
        available mais 2 runs None (L189 de `_is_tool_unavailable_failure`) est
        EXCLU ici : une source reseau injoignable y tombe (timeout/IO alors que
        ffprobe/mediainfo se lancent) et DOIT alimenter le breaker. Sinon le
        compteur n'incremente jamais, la source ne passe jamais DEGRADED, et
        chaque fichier du NAS en panne paie le timeout adaptatif complet
        (~41h de hang que le module dit prevenir).

        Cas WinError 2 reel (path obsolete) : il echoue aussi sur les fichiers
        LOCAUX, ou record_failure est un no-op (extract_network_source -> None) ;
        et le cache reste protege par `_is_tool_unavailable_failure` (inchange).
        Alimenter le breaker ici est donc sans risque.
        """
        if backend == "none":
            return False
        if backend == "mediainfo":
            return not mediainfo_tool.available
        if backend == "ffprobe":
            return not ffprobe_tool.available
        # auto : seulement si AUCUN binaire n'est lancable (pas de probe possible).
        return not mediainfo_tool.available and not ffprobe_tool.available

    def _maybe_purge_obsolete_tool_paths(
        self,
        *,
        settings: Optional[Dict[str, Any]],
        mediainfo_tool: ToolStatus,
        ffprobe_tool: ToolStatus,
    ) -> None:
        """Fix audit 2026-05-25 (v1.5.5) Vague K (FIX 2) : auto-invalide les paths
        obsoletes dans settings.json quand le tool est marque introuvable.

        Logique :
        - Si settings contient un mediainfo_path explicite ET mediainfo_tool est
          marque unavailable (le path n'a pas pu etre resolu vers un binaire
          executable) -> on tente d'invalider via settings_facade.
        - Idem ffprobe.

        Idempotent : si pas de settings persistable, ne fait rien.
        Best-effort : aucune exception ne doit casser la route probe.
        """
        if not isinstance(settings, dict):
            return
        raw_mi = str(settings.get("mediainfo_path") or "").strip()
        raw_ff = str(settings.get("ffprobe_path") or "").strip()
        purge_mi = bool(raw_mi) and not mediainfo_tool.available
        purge_ff = bool(raw_ff) and not ffprobe_tool.available
        if not purge_mi and not purge_ff:
            return
        if purge_mi:
            logger.warning(
                "mediainfo path obsolete (%s), purged from settings (Fix v1.5.5 Vague K)",
                raw_mi,
            )
        if purge_ff:
            logger.warning(
                "ffprobe path obsolete (%s), purged from settings (Fix v1.5.5 Vague K)",
                raw_ff,
            )
        # Best-effort : essaie de persister via api.settings si dispo (settings
        # passe en dict est souvent un snapshot non-persistable, on log juste).
        # La persistance reelle se fait via l'endpoint runtime/recheck_probe_tools
        # appele depuis l'UI au reload. Ici on invalide le cache in-memory.
        try:
            self.invalidate_tools_status_cache()
        except (AttributeError, RuntimeError):
            pass

    def _cache_key(self, media_path: Path, backend: str) -> Optional[Dict[str, Any]]:
        try:
            st = media_path.stat()
        except (KeyError, OSError, PermissionError, TypeError, ValueError) as exc:
            logger.debug("Probe cache key ignoree (stat impossible) path=%s err=%s", media_path, exc)
            return None
        return {
            "path": str(media_path.resolve()),
            "size": int(st.st_size),
            "mtime": float(st.st_mtime),
            "tool": str(backend),
        }

    def _get_probe_cache_combined(self, cache_key: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """ITER13 CACHE_PROBE : lecture cache DB + fallback cache disque JSON.

        Ordre :
        1. DB (autoritatif, rapide local SSD).
        2. Si DB miss ou DB exception (NAS lent, BrokenPipeError, lock SQLite),
           tente le cache disque JSON.
        3. Si hit disque mais DB miss, on retour-promote vers la DB en best-effort
           (warm-up DB pour les prochains scans).

        Backward-compat : si la DB est OK et hit, comportement strictement
        identique a l'ancien code (un seul lookup DB).
        """
        try:
            cached = self.store.probe.get_probe_cache(**cache_key)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            # DB indisponible (NAS lent, lock SQLite, BrokenPipeError) -> on
            # tente quand meme le cache disque.
            logger.warning(
                "Cache probe DB lecture echouee path=%s err=%s (fallback disque)",
                cache_key.get("path"),
                exc,
            )
            cached = None

        if cached:
            return cached

        # Fallback : cache disque JSON. Couche secondaire, ne casse jamais.
        disk_cached = get_disk_cache(**cache_key)
        if disk_cached is None:
            return None

        # Warm-up DB : si hit disque, on tente de re-promouvoir vers la DB
        # pour que les prochains lookups soient rapides. Best-effort.
        try:
            self.store.probe.upsert_probe_cache(
                **cache_key,
                raw_json=disk_cached["raw_json"],
                normalized_json=disk_cached["normalized_json"],
                ts=disk_cached.get("ts", time.time()),
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.debug("Warm-up DB depuis cache disque ignore path=%s err=%s", cache_key.get("path"), exc)
        return disk_cached

    def _upsert_probe_cache_combined(
        self,
        cache_key: Dict[str, Any],
        *,
        raw_json: Dict[str, Any],
        normalized_dict: Dict[str, Any],
    ) -> None:
        """ITER13 CACHE_PROBE : ecrit dans cache DB ET cache disque.

        Best-effort : si l'une des deux ecritures echoue, on logue mais on
        continue. La DB reste autoritative pour les futurs lookups via
        ProbeRepository ; le disque est resilience supplementaire.
        """
        ts_now = time.time()
        # DB d'abord (compat existant).
        try:
            self.store.probe.upsert_probe_cache(
                **cache_key,
                raw_json=raw_json,
                normalized_json=normalized_dict,
                ts=ts_now,
            )
        except (OSError, TypeError, ValueError) as exc:
            logger.warning(
                "Ecriture cache probe DB ignoree path=%s err=%s",
                cache_key.get("path"),
                exc,
            )
        # Disque ensuite (best-effort, n'altere jamais le retour probe).
        upsert_disk_cache(
            **cache_key,
            raw_json=raw_json,
            normalized_json=normalized_dict,
            ts=ts_now,
        )

    def _degraded_source_payload(
        self, media_path: Path, backend: str, exc: SourceDegradedError
    ) -> Dict[str, Any]:
        """Payload retourne quand la source UNC est DEGRADED (Iter13 CIRCUIT_BREAKER).

        Le payload est `ok=true` (la route REST a fonctionne) mais
        `degraded_source=true`, `normalized` reflete probe FAILED, et un message
        lisible est attache. Le caller (quality_report_support) DOIT detecter
        `degraded_source` pour afficher "indisponible" en clair :
        PAS score invente, PAS ligne disparue, PAS 0 trompeur (memoire user
        "degradation JAMAIS silencieuse").

        Identification DECOUPLEE preservee : l'item reste identifiable+renommable
        via TMDb/NFO/filename, on ne lit juste pas les metadonnees techniques
        cote probe (acquis iter4).
        """
        source = extract_network_source(media_path) or ""
        message = (
            f"Source reseau '{source}' degradee (circuit breaker ouvert) : probe non tente. "
            f"Detail : {exc}"
        )
        normalized_obj = normalize_probe(
            media_path=media_path,
            raw_mediainfo=None,
            raw_ffprobe=None,
            backend=backend,
            messages=[message],
        )
        return {
            "ok": True,
            "cache_hit": False,
            "degraded_source": True,
            "source": source,
            "normalized": normalized_obj.to_dict(),
            "raw_json": {"mediainfo": None, "ffprobe": None},
            "sources": {
                "backend": backend,
                "tools": {},
                "breaker_message": message,
            },
        }

    def probe_file(self, *, media_path: Path, settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = _normalize_probe_settings(settings)
        backend = cfg["probe_backend"]

        cache_key = self._cache_key(media_path, backend)
        if cache_key is not None and backend != "none":
            cached = self._get_probe_cache_combined(cache_key)
            if cached:
                normalized_cached = (
                    cached.get("normalized_json") if isinstance(cached.get("normalized_json"), dict) else {}
                )
                raw_cached = (
                    cached.get("raw_json")
                    if isinstance(cached.get("raw_json"), dict)
                    else {"mediainfo": None, "ffprobe": None}
                )
                return {
                    "ok": True,
                    "cache_hit": True,
                    "normalized": normalized_cached,
                    "raw_json": raw_cached,
                    "sources": {
                        "backend": backend,
                        "tools": {},
                    },
                }

        # Iter13 CIRCUIT_BREAKER : si la source UNC est DEGRADED, on saute
        # le subprocess immediatement (pas de timeout 30s gaspille). No-op
        # sur paths locaux (C:\, D:\). Le payload retourne marque
        # `degraded_source=true` -> la couche quality affiche "indisponible".
        if backend != "none":
            try:
                self._source_breaker.check_or_raise(media_path)
            except SourceDegradedError as breaker_exc:
                logger.info(
                    "Probe skip (source degraded) path=%s reason=%s",
                    media_path,
                    breaker_exc,
                )
                return self._degraded_source_payload(media_path, backend, breaker_exc)

        # PERF-1 : utilise le cache au lieu de relancer 2 subprocess `--version` par film
        tools = self._get_tools_cached(cfg)
        messages: List[str] = []
        raw_mediainfo: Optional[Dict[str, Any]] = None
        raw_ffprobe: Optional[Dict[str, Any]] = None

        mediainfo_tool: ToolStatus = tools["mediainfo"]
        ffprobe_tool: ToolStatus = tools["ffprobe"]

        # ITER13 TIMEOUT_ADAPTATIF : remplace le couperet unique cfg["probe_timeout_s"]
        # par un timeout proportionne a la taille du fichier (base + per_gb * GB,
        # borne [floor, ceiling]). Le settings legacy `probe_timeout_s` reste utilise
        # comme base si pas de `probe_timeout_base_s` (retro-compat ABSOLUE).
        # Cf cinesort/infra/probe/adaptive_timeout.py.
        adaptive_cfg = resolve_adaptive_timeout_config(settings)
        adaptive_timeout_s = compute_adaptive_timeout(media_path, config=adaptive_cfg)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Probe timeout adaptatif path=%s timeout=%.1fs (base=%.1fs per_gb=%.1fs)",
                media_path,
                adaptive_timeout_s,
                adaptive_cfg.base_s,
                adaptive_cfg.per_gb_s,
            )

        if backend == "none":
            messages.append("Probe desactivee (probe_backend=none).")
        elif backend == "mediainfo":
            if not mediainfo_tool.available:
                messages.append("MediaInfo manquant: probe partielle.")
            else:
                raw_mediainfo, mi_msgs = run_mediainfo_json(
                    tool_path=mediainfo_tool.path,
                    media_path=media_path,
                    runner=self.runner,
                    timeout_s=adaptive_timeout_s,
                )
                messages.extend(mi_msgs)
        elif backend == "ffprobe":
            if not ffprobe_tool.available:
                messages.append("ffprobe manquant: probe partielle.")
            else:
                raw_ffprobe, ff_msgs = run_ffprobe_json(
                    tool_path=ffprobe_tool.path,
                    media_path=media_path,
                    runner=self.runner,
                    timeout_s=adaptive_timeout_s,
                )
                messages.extend(ff_msgs)
        else:  # auto
            if not mediainfo_tool.available:
                messages.append("MediaInfo manquant (mode auto).")
            if not ffprobe_tool.available:
                messages.append("ffprobe manquant (mode auto).")
            if mediainfo_tool.available:
                raw_mediainfo, mi_msgs = run_mediainfo_json(
                    tool_path=mediainfo_tool.path,
                    media_path=media_path,
                    runner=self.runner,
                    timeout_s=adaptive_timeout_s,
                )
                messages.extend(mi_msgs)
            if ffprobe_tool.available:
                raw_ffprobe, ff_msgs = run_ffprobe_json(
                    tool_path=ffprobe_tool.path,
                    media_path=media_path,
                    runner=self.runner,
                    timeout_s=adaptive_timeout_s,
                )
                messages.extend(ff_msgs)

        normalized_obj: NormalizedProbe = normalize_probe(
            media_path=media_path,
            raw_mediainfo=raw_mediainfo,
            raw_ffprobe=raw_ffprobe,
            backend=backend,
            messages=messages,
        )
        normalized_dict = normalized_obj.to_dict()

        raw_json = {
            "mediainfo": raw_mediainfo,
            "ffprobe": raw_ffprobe,
        }
        # Fix audit 2026-05-25 (v1.5.5) Vague K (FIX 4) : ne PAS polluer le cache
        # quand le probe a echoue parce que le tool est introuvable / non lance.
        # Distinguer :
        #  - "tool unavailable" (transient : path obsolete, winget pas installe)
        #    -> on ne cache PAS, sinon meme apres fix le cache hit retourne FAILED
        #  - "file corrupted" (persistent : ffprobe a tourne mais a echoue)
        #    -> on cache normalement, le fichier est reellement casse
        tool_unavailable = self._is_tool_unavailable_failure(
            backend=backend,
            raw_mediainfo=raw_mediainfo,
            raw_ffprobe=raw_ffprobe,
            mediainfo_tool=mediainfo_tool,
            ffprobe_tool=ffprobe_tool,
        )
        if tool_unavailable:
            # Fix audit 2026-05-25 (v1.5.5) Vague K (FIX 2) : invalider auto le
            # path obsolete dans settings.json pour que le prochain run fallback
            # PATH winget. UI sera notifiee au reload.
            self._maybe_purge_obsolete_tool_paths(
                settings=settings,
                mediainfo_tool=mediainfo_tool,
                ffprobe_tool=ffprobe_tool,
            )

        if cache_key is not None and backend != "none" and not tool_unavailable:
            # ITER13 CACHE_PROBE : ecrit DB + disque (best-effort, jamais bloquant).
            self._upsert_probe_cache_combined(
                cache_key,
                raw_json=raw_json,
                normalized_dict=normalized_dict,
            )
        elif tool_unavailable:
            logger.debug(
                "Cache probe NON ecrit pour %s (tool indisponible, evite pollution)",
                media_path,
            )

        # Iter13 CIRCUIT_BREAKER : enregistrer succes / echec sur la source UNC.
        # On NE penalise PAS quand le tool est globalement indisponible (binaire
        # absent du PATH) : c'est une cause locale, pas un probleme de la source.
        # Idem si backend == "none" (probe desactive).
        # No-op sur paths locaux (extract_network_source retourne None).
        # AUDIT 2026-06-11 (R3e, gap[4]) : on utilise la variante STRICTE
        # `_is_tool_definitely_unavailable` (PAS le `tool_unavailable` du cache).
        # Une source reseau injoignable en auto rend les 2 runs None par
        # timeout/IO -> l'ancien `tool_unavailable` (L189) la classait a tort
        # "tool indisponible" et SAUTAIT ce feed, donc le breaker ne degradait
        # jamais et le NAS en panne re-timeoutait sur chaque fichier (~41h).
        breaker_tool_unavailable = self._is_tool_definitely_unavailable(
            backend=backend,
            mediainfo_tool=mediainfo_tool,
            ffprobe_tool=ffprobe_tool,
        )
        if backend != "none" and not breaker_tool_unavailable:
            probe_succeeded = raw_mediainfo is not None or raw_ffprobe is not None
            if probe_succeeded:
                self._source_breaker.record_success(media_path)
            else:
                just_degraded = self._source_breaker.record_failure(media_path)
                if just_degraded:
                    # Notification visible : la source UNC vient juste de
                    # basculer en DEGRADED, l'utilisateur doit etre informe.
                    logger.warning(
                        "Source reseau DEGRADED pour %s : circuit breaker ouvert "
                        "(probes suivantes immediates jusqu'a reset)",
                        extract_network_source(media_path),
                    )

        return {
            "ok": True,
            "cache_hit": False,
            "normalized": normalized_dict,
            "raw_json": raw_json,
            "sources": {
                "backend": backend,
                "tools": {k: v.to_dict() for k, v in tools.items()},
            },
        }

    def _try_cache_lookup(self, media_path: Path, backend: str) -> Optional[Dict[str, Any]]:
        """V5-04 : cache lookup utilise AVANT submit au pool — evite subprocess inutile.

        ITER13 CACHE_PROBE : passe par `_get_probe_cache_combined` (DB +
        fallback disque JSON). Comportement DB-hit identique a avant.

        Retourne le resultat formatte si hit, None sinon (ou si cache desactive).
        """
        if backend == "none":
            return None
        cache_key = self._cache_key(media_path, backend)
        if cache_key is None:
            return None
        cached = self._get_probe_cache_combined(cache_key)
        if not cached:
            return None
        normalized_cached = cached.get("normalized_json") if isinstance(cached.get("normalized_json"), dict) else {}
        raw_cached = (
            cached.get("raw_json") if isinstance(cached.get("raw_json"), dict) else {"mediainfo": None, "ffprobe": None}
        )
        return {
            "ok": True,
            "cache_hit": True,
            "normalized": normalized_cached,
            "raw_json": raw_cached,
            "sources": {
                "backend": backend,
                "tools": {},
            },
        }

    def probe_files(
        self,
        *,
        media_paths: List[Path],
        settings: Optional[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """Probe un lot de fichiers en parallele (ThreadPoolExecutor) si active.

        V5-04 (Polish Total v7.7.0, R5-STRESS-1) : ffprobe / mediainfo sont I/O-bound
        (attente subprocess) — ThreadPool ideal, pas besoin de multiprocessing.

        Comportement :
        - Cache lookup AVANT submit au pool (evite subprocess inutile sur cache hit).
        - Si parallelism_enabled + N>1 films a probe-er reellement : ThreadPool.
        - Sinon mono-thread (compatibilite, et plus rapide pour 1 seul element).
        - Preserve l'ordre des resultats via dict de mapping path -> result.
        - Workers count clampe : auto = min(cpu_count(), 8), max 16.

        Cible perf : 10k films probe < 1h (vs 7.6h mono-thread sur estimation
        2-3s/probe avec 4-8 workers).
        """
        cfg = _normalize_probe_settings(settings)
        backend = cfg["probe_backend"]
        results: Dict[str, Dict[str, Any]] = {}

        if not media_paths:
            return results

        # 1) Cache lookup AVANT submit — evite subprocess inutile.
        # Dedup input par path (cas list avec doublons : meme film passe 2x).
        seen_keys: set = set()
        to_probe: List[Path] = []
        for mp in media_paths:
            key = str(mp)
            if key in seen_keys:
                continue  # deduplication input
            seen_keys.add(key)
            cached_result = self._try_cache_lookup(mp, backend)
            if cached_result is not None:
                results[key] = cached_result
            else:
                to_probe.append(mp)

        if not to_probe:
            return results

        # 2) Decision parallel vs sequential
        use_pool = cfg["probe_parallelism_enabled"] and len(to_probe) > 1

        if not use_pool:
            for mp in to_probe:
                results[str(mp)] = self.probe_file(media_path=mp, settings=settings)
            return results

        # 3) Parallel via ThreadPoolExecutor — preservation ordre via dict mapping
        workers = min(cfg["probe_workers"], len(to_probe))
        logger.info(
            "Probe batch parallel: %d films, %d workers, backend=%s",
            len(to_probe),
            workers,
            backend,
        )
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="probe") as ex:
            future_to_path = {ex.submit(self.probe_file, media_path=mp, settings=settings): mp for mp in to_probe}
            for future in as_completed(future_to_path):
                mp = future_to_path[future]
                try:
                    results[str(mp)] = future.result()
                except subprocess.TimeoutExpired as exc:
                    # ITER13 RETRY_BACKOFF : symetrie avec les backends. Avant,
                    # TimeoutExpired pas dans le tuple -> casse `as_completed`
                    # pour tout le batch parallel (cf BILAN_ITER13 §2).
                    logger.warning("Probe parallel timeout path=%s err=%s", mp, exc)
                    results[str(mp)] = {
                        "ok": False,
                        "cache_hit": False,
                        "normalized": {},
                        "raw_json": {"mediainfo": None, "ffprobe": None},
                        "sources": {"backend": backend, "tools": {}},
                        "error": f"timeout: {exc}",
                    }
                except (AttributeError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error) as exc:
                    # R8-024 (F2-d) : +AttributeError +sqlite3.Error. Une OperationalError
                    # (ecriture cache probe sur verrou DB) sortait de la boucle as_completed
                    # -> tout le LOT de probe restant etait abandonne (films scores au nom seul).
                    # Desormais : entree ok:False par fichier (comme la branche TimeoutExpired).
                    logger.warning("Probe parallel failed path=%s err=%s", mp, exc)
                    results[str(mp)] = {
                        "ok": False,
                        "cache_hit": False,
                        "normalized": {},
                        "raw_json": {"mediainfo": None, "ffprobe": None},
                        "sources": {"backend": backend, "tools": {}},
                        "error": str(exc),
                    }
        return results
