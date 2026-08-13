from __future__ import annotations

import inspect
import logging
import os
import sqlite3
import threading
import time
import traceback
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from cinesort.domain.run_models import RunSnapshot, RunStatus
from cinesort.infra.db import SQLiteStore
from cinesort.infra.db.sqlite_store import portee_de_requete
from cinesort.infra.log_context import clear_run_id, set_run_id
from cinesort.infra.run_id import RUN_ID_PATTERN, generate_run_id, normalize_or_generate_run_id

_logger = logging.getLogger(__name__)


JobFn = Callable[[Callable[[], bool]], Optional[Dict[str, Any]]]
_TERMINAL = {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED}
_ACTIVE = {RunStatus.PENDING, RunStatus.RUNNING}
# H15 fix (hotfix2) : ensemble etendu pour `_active_run_locked`. Un run
# PAUSED ou AWAITING_VALIDATION possede encore un thread worker ou un
# verrou logique sur le store : autoriser `start_job` a en lancer un nouveau
# en parallele aboutirait a deux jobs ecrivant simultanement sur la meme
# base. SAVED est inclus pour la meme raison (l'operateur peut reprendre
# a tout moment). On garde `_ACTIVE` strict pour la semantique `running`
# exposee dans RunSnapshot afin de ne pas casser la backward compat des
# consommateurs (UI, logs, get_status).
_RESERVED = {
    RunStatus.PENDING,
    RunStatus.RUNNING,
    RunStatus.PAUSED,
    RunStatus.SAVED,
    RunStatus.AWAITING_VALIDATION,
}


@dataclass
class _RuntimeRun:
    run_id: str
    cancel_event: threading.Event
    thread: Optional[threading.Thread]
    snapshot: RunSnapshot
    debug_log: Optional[Callable[[str], None]]
    # V8-01 spec 08 Traitement : signaling pause/resume. Le worker job_fn
    # peut interroger `pause_event.is_set()` au meme titre que `should_cancel()`
    # pour suspendre proprement la boucle. La pause est persistee en DB via
    # RunRepository.mark_run_paused, le runner ne fait que signaler.
    pause_event: Optional[threading.Event] = None


class JobRunner:
    """Orchestrateur de jobs (scan/apply) en thread, avec persistance d'état.

    Gère un seul run actif à la fois, expose `start_job`, `request_cancel` et
    `get_status`. Les snapshots sont persistés dans `SQLiteStore` et exposés via
    `RunSnapshot` pour l'UI.
    """

    def __init__(self, store: SQLiteStore, debug_logger: Optional[Callable[[str], None]] = None):
        self._store = store
        self._lock = threading.RLock()
        self._runs: Dict[str, _RuntimeRun] = {}
        self._active_run_id: Optional[str] = None
        self._debug_logger = debug_logger

    def _debug(self, message: str, run_debug: Optional[Callable[[str], None]] = None) -> None:
        logger = run_debug or self._debug_logger
        if not logger:
            return
        try:
            logger(message)
        # except Exception intentionnel : boundary top-level
        except Exception as exc:
            if str(os.environ.get("CINESORT_DEBUG", "")).strip().lower() in {"1", "true", "yes", "on", "debug"}:
                try:
                    print(f"[JobRunner] debug logger failure: {exc}", flush=True)
                except (KeyError, TypeError, ValueError):
                    return

    def _write_crash_for_run(self, run_id: str, header: str, tb_text: str) -> None:
        try:
            row = self._store.run.get_run(run_id)
            if not row:
                return
            # Path("") -> Path(".") est truthy : tester la chaine brute, sinon
            # un state_dir vide ferait ecrire crash.txt dans le CWD du process.
            state_dir_raw = str(row.get("state_dir") or "").strip()
            if not state_dir_raw:
                return
            state_dir = Path(state_dir_raw)
            run_dir = state_dir / "runs" / f"tri_films_{run_id}"
            run_dir.mkdir(parents=True, exist_ok=True)
            content = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {header}\n\n{tb_text.rstrip()}\n"
            run_dir.joinpath("crash.txt").write_text(content, encoding="utf-8")
        # except Exception intentionnel : boundary top-level
        except Exception as exc:
            self._debug(f"_write_crash_for_run warning run_id={run_id}: {exc}")

    def _safe_stats(self, stats: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        return stats if isinstance(stats, dict) else None

    def _set_snapshot(self, run_id: str, **changes: Any) -> None:
        rt = self._runs.get(run_id)
        if not rt:
            return
        rt.snapshot = replace(rt.snapshot, **changes)

    def _should_cancel_factory(self, run_id: str) -> Callable[[], bool]:
        def _should_cancel() -> bool:
            with self._lock:
                rt = self._runs.get(run_id)
                if not rt:
                    return True
                return rt.cancel_event.is_set()

        return _should_cancel

    def get_cancel_event(self, run_id: str) -> Optional[threading.Event]:
        """R8-037 (F4) : expose le `cancel_event` d'un run pour câbler l'annulation
        coopérative des sous-tâches (ex. batch perceptuel post-scan) sur le MÊME
        event que `request_cancel` met (`rt.cancel_event`). Sans ça, le batch lisait
        `api._perceptual_cancel_event` jamais assigné -> checks d'annulation inertes."""
        with self._lock:
            rt = self._runs.get(run_id)
            return rt.cancel_event if rt else None

    def _invoke_job_fn(
        self,
        job_fn: JobFn,
        should_cancel: Callable[[], bool],
        should_pause: Callable[[], bool],
    ) -> Optional[Dict[str, Any]]:
        """VN-E.3 : invoque job_fn avec injection backward-compatible.

        Strategie : si le job_fn accepte `should_pause` (kwarg explicite
        ou **kwargs), on l'injecte. Sinon, on appelle avec uniquement
        `should_cancel` comme avant.

        On capture les TypeError signature pour fallback (defensif :
        inspect.signature peut echouer sur certains callables C/builtins).
        """
        try:
            sig = inspect.signature(job_fn)
        # except Exception : inspect peut lever sur builtins/C-callables
        except (TypeError, ValueError):
            return job_fn(should_cancel)

        params = sig.parameters
        accepts_should_pause = "should_pause" in params or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
        if accepts_should_pause:
            # AUDIT 2026-06-10 (REAL 2/2) : valider la LIAISON des arguments avant
            # d'appeler, au lieu d'un except TypeError autour de l'appel. La
            # signature confirme deja que should_pause est accepte ; un TypeError
            # leve PENDANT l'execution vient donc du CORPS du job (donnees
            # invalides), pas de la signature. L'ancien except rejouait alors le
            # job ENTIER -> double effets de bord (deplacements, journal, notifs).
            # sig.bind() teste la liaison sans executer : seul un vrai mismatch
            # de signature retombe sur le fallback legacy ; un TypeError du corps
            # se propage normalement (pas de re-run).
            try:
                sig.bind(should_cancel, should_pause=should_pause)
            except TypeError:
                return job_fn(should_cancel)
            return job_fn(should_cancel, should_pause=should_pause)
        return job_fn(should_cancel)

    def _should_pause_factory(self, run_id: str) -> Callable[[], bool]:
        """VN-E.3 : factory pour la pause cooperative.

        Le job_fn (scan/apply/plan/rescan) peut interroger ce callable
        dans sa boucle principale pour suspendre proprement sa progression
        tant que `pause_event` est pose. Symetrique de
        `_should_cancel_factory`. Retourne False si run inconnu (defensif :
        pas de blocage).

        Note : la cancellation prevaut sur la pause — c'est au job_fn de
        verifier `should_cancel()` apres chaque sleep pour sortir
        immediatement si necessaire (cf. tests/test_pause_cooperative_v77).
        """

        def _should_pause() -> bool:
            with self._lock:
                rt = self._runs.get(run_id)
                if not rt or rt.pause_event is None:
                    return False
                return rt.pause_event.is_set()

        return _should_pause

    def _current_db_status(self, run_id: str) -> Optional[str]:
        """Lit le statut DB courant (sans modifier l'etat memoire). C4 fix.

        Utilise par les transitions terminales pour eviter d'ecraser un
        PAUSED/SAVED/AWAITING_VALIDATION qu'un thread API aurait persiste
        concurremment (cf. RunRepository.mark_run_paused, dont l'UPDATE
        n'a pas de WHERE status pour empecher l'ecrasement inverse cote
        runner). Defensif : retourne None si DB inaccessible.
        """
        try:
            row = self._store.run.get_run(run_id)
        # except Exception : best-effort, on prefere autoriser la transition
        except Exception as exc:
            self._debug(f"_current_db_status warning run_id={run_id}: {exc}")
            return None
        if not row:
            return None
        return str(row.get("status") or "") or None

    def _is_user_held_state(self, db_status: Optional[str]) -> bool:
        """True si la DB indique un etat sous controle operateur (C4 fix).

        Les transitions terminales (DONE/CANCELLED/FAILED) initiees par le
        worker ne doivent PAS ecraser ces etats : c'est l'operateur (via
        resume / save) qui decide quand le run quitte la pause.
        """
        if not db_status:
            return False
        return db_status in (
            RunStatus.PAUSED.value,
            RunStatus.SAVED.value,
            RunStatus.AWAITING_VALIDATION.value,
        )

    def _should_skip_terminal(
        self,
        run_id: str,
        *,
        should_cancel_fn: Optional[Callable[[], bool]] = None,
    ) -> tuple[bool, Optional[str]]:
        """STATE-MACHINE-001 fix : decide si la transition terminale doit etre skippee.

        Retourne `(skip, db_status_before)`.

        Logique :
        - Si la DB est dans un etat user-held (PAUSED/SAVED/AWAITING_VALIDATION),
          on skippe normalement (protection C4 contre l'ecrasement par un
          job_fn qui retournerait pendant que l'API pose PAUSE).
        - SAUF si la cancellation a ete explicitement demandee par l'operateur
          (`should_cancel_fn()` retourne True). Dans ce cas, l'intention
          operateur prevaut : on autorise la transition CANCELLED meme si la
          DB est PAUSED. Sans cette exception, annuler un run paused laisse
          le run bloque en PAUSED a perpetuite (slot actif jamais libere).
        """
        db_status_before = self._current_db_status(run_id)
        if not self._is_user_held_state(db_status_before):
            return False, db_status_before
        # Etat user-held detecte : on skippe SAUF si cancel explicite.
        if should_cancel_fn is not None:
            try:
                if should_cancel_fn():
                    return False, db_status_before
            # except Exception : defensif, on retombe sur le skip protecteur
            except Exception as exc:
                self._debug(f"_should_skip_terminal should_cancel_fn raised run_id={run_id}: {exc}")
        return True, db_status_before

    def _ensure_run_left_running(
        self,
        run_id: str,
        *,
        error_message: Optional[str],
        run_debug: Optional[Callable[[str], None]],
    ) -> None:
        """Issue #515 — filet de securite : un run ne reste JAMAIS sur RUNNING.

        Appele depuis le `finally` de `_run_worker`, donc emprunte aussi le
        chemin ou le gestionnaire d'echec a lui-meme leve : `mark_run_failed`
        tape une DB verrouillee (antivirus Windows), un disque plein ou un
        schema corrompu, l'exception secondaire se propage AVANT la transition
        FAILED, et le run reste RUNNING en base ET en memoire pour toujours.
        L'utilisateur voit un traitement eternellement en cours.

        Un `except` de plus dans le gestionnaire d'echec ne suffirait pas : il
        faudrait le repeter a chaque nouvelle ecriture DB de ce bloc. La
        garantie est ici structurelle — c'est le `finally` qui la porte.

        Ne touche a rien quand :
        - le snapshot a deja transite (statut terminal) ;
        - le run est sous controle operateur (PAUSED / SAVED /
          AWAITING_VALIDATION), en memoire ou en base : la protection C4 prime ;
        - la DB a bien transite et seul le snapshot memoire est en retard (on
          s'aligne alors sur la DB au lieu d'inventer un FAILED).
        """
        with self._lock:
            rt = self._runs.get(run_id)
            snapshot_status = rt.snapshot.status if rt else None
        if snapshot_status is None or snapshot_status in _TERMINAL:
            return
        if self._is_user_held_state(snapshot_status.value):
            return

        db_status = self._current_db_status(run_id)
        if self._is_user_held_state(db_status):
            return
        try:
            db_state = RunStatus(str(db_status)) if db_status else None
        except (TypeError, ValueError):
            db_state = None
        if db_state in _TERMINAL:
            with self._lock:
                self._set_snapshot(run_id, status=db_state, running=False, done=True)
            self._debug(f"worker safety net aligned snapshot on DB={db_status} run_id={run_id}", run_debug)
            return

        ended_ts = time.time()
        message = error_message or "Run interrompu sans transition terminale (job_runner)"
        try:
            self._store.run.mark_run_failed(run_id, error_message=message, ended_ts=ended_ts)
        # except Exception : la DB est peut-etre injoignable — c'est justement
        # le scenario qui amene ici. On ne peut alors plus rien pour la ligne
        # `runs` (le nettoyage des runs orphelins au boot la reprendra), mais
        # l'etat memoire, lui, DOIT quitter RUNNING.
        except Exception as exc:
            _logger.error("job: transition FAILED impossible en base run_id=%s: %s", run_id, exc)
            self._debug(f"worker safety net mark_run_failed failed run_id={run_id}: {exc}", run_debug)
        with self._lock:
            self._set_snapshot(
                run_id,
                status=RunStatus.FAILED,
                ended_ts=ended_ts,
                running=False,
                done=True,
                error=message,
            )
        _logger.warning("job: run force en FAILED par le filet de securite run_id=%s", run_id)
        self._debug(f"worker safety net forced FAILED run_id={run_id}", run_debug)

    def _active_run_locked(self) -> Optional[_RuntimeRun]:
        if not self._active_run_id:
            return None
        rt = self._runs.get(self._active_run_id)
        if not rt:
            self._active_run_id = None
            return None
        # H15 fix (hotfix2) : un thread suspendu (PAUSED) ou en attente de
        # validation operateur (AWAITING_VALIDATION/SAVED) detient encore le
        # slot actif. Sans cette extension, `start_job` autorisait un second
        # run en parallele, et deux threads ecrivaient simultanement sur le
        # meme store SQLite (corruption metier).
        if rt.snapshot.status in _RESERVED:
            return rt
        self._active_run_id = None
        return None

    #: Bornes du tirage d'un run_id de remplacement. Au-dela, on preferera un
    #: echec bruyant a une boucle infinie : `normalize_or_generate_run_id` tire
    #: sur l'horodatage, donc une collision persistante signale un probleme reel
    #: (horloge figee, base corrompue) qu'il ne faut pas masquer.
    _TIRAGES_RUN_ID_MAX = 8

    def _run_id_de_remplacement(self) -> str:
        """Tire un run_id neuf et VERIFIE qu'il est reellement libre.

        #984 : les deux chemins de remplacement tiraient un identifiant sans
        rappeler la garde. Or `insert_run_pending` ne detecte que les collisions
        dans `runs` — une collision du REMPLACANT avec une ligne orpheline
        creerait donc un run qui herite de ses donnees, c'est-a-dire exactement
        le defaut corrige, un niveau plus bas.
        """
        candidat = normalize_or_generate_run_id(None)
        for _ in range(self._TIRAGES_RUN_ID_MAX):
            if candidat not in self._runs and not self._store.run.run_id_est_utilise(candidat):
                return candidat
            candidat = normalize_or_generate_run_id(None)
        raise RuntimeError(
            f"Impossible de tirer un run_id libre en {self._TIRAGES_RUN_ID_MAX} essais — "
            f"horloge figee ou base incoherente."
        )

    def start_job(
        self,
        *,
        job_fn: JobFn,
        root: str,
        state_dir: str,
        config: Dict[str, Any],
        run_id_hint: Optional[str] = None,
        debug_log: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Démarre un nouveau job en thread daemon et renvoie son `run_id`.

        Lève `RuntimeError` si un run est déjà actif.

        Génère un `run_id` unique si `run_id_hint` est absent. Si un
        `run_id_hint` EXPLICITE entre en collision, on lève au lieu de lui
        substituer un autre identifiant : l'appelant (start_plan) a déjà créé
        le dossier `tri_films_<hint>` et le `RunState` sous cet id, et le
        `job_fn` a capturé le même. Substituer faisait diverger `started_run_id`
        du hint, ce que start_plan traduisait en erreur interne APRÈS que le
        thread ait démarré : un scan fantôme, non pilotable, écrivant son plan
        dans le dossier de l'ancien id pendant que la ligne `runs` vivait sous
        le nouveau. Lever avant tout démarrage de thread supprime ce cas.

        Un hint EXPLICITE hors format canonique est refusé pour la même raison :
        `normalize_or_generate_run_id` lui aurait substitué un identifiant neuf,
        c'est-à-dire exactement la divergence que le refus de collision
        ci-dessous supprime, mais par un autre chemin. Le seul appelant du dépôt
        (`run_flow_support:_start_plan_impl`) passe un id issu de
        `reserve_unique_run`, donc déjà canonique : ce refus ne change rien au
        flux réel, il rend le contrat vrai sur TOUTE la surface publique.
        """
        created_ts = time.time()
        if run_id_hint:
            if not RUN_ID_PATTERN.match(run_id_hint):
                raise RuntimeError(f"Le run_id demande n'est pas au format attendu : {run_id_hint!r}")
            candidate = run_id_hint
            run_id = run_id_hint
        else:
            candidate = generate_run_id()
            run_id = normalize_or_generate_run_id(candidate)
        run_debug = debug_log or self._debug_logger
        self._debug(
            f"start_job called candidate={candidate} normalized_run_id={run_id} root={root} state_dir={state_dir}",
            run_debug,
        )

        with self._lock:
            active = self._active_run_locked()
            if active:
                self._debug("start_job refused: active run already in progress", run_debug)
                raise RuntimeError("Un run est deja en cours")

            # Collision memoire/DB sous verrou, ORPHELINES COMPRISES (#984 : `get_run`
            #  ne voyait que `runs` ; cf. `run_id_est_utilise`).
            #  - hint EXPLICITE : on refuse, sans demarrer de thread (cf docstring).
            #  - pas de hint : rien n'existe sous cet id, la substitution est neutre.
            if run_id in self._runs or self._store.run.run_id_est_utilise(run_id):
                if run_id_hint:
                    self._debug(f"start_job refused: run_id hint {run_id} already used", run_debug)
                    raise RuntimeError(f"Le run_id demande est deja utilise : {run_id}")
                self._debug(f"start_job run_id collision for {run_id}, generating fallback id", run_debug)
                run_id = self._run_id_de_remplacement()

            # Sprint 2 audit P0 #6 : insert_run_pending peut encore lever IntegrityError
            # malgre la pre-verification get_run() ci-dessus, en cas de race entre
            # plusieurs threads (TOCTOU) ou entre deux processus. Meme arbitrage que
            # ci-dessus : on ne regenere QUE lorsque aucun hint explicite n'a ete
            # fourni, pour ne jamais faire diverger l'id rendu de l'id du hint.
            try:
                self._store.run.insert_run_pending(
                    run_id=run_id,
                    root=str(root),
                    state_dir=str(state_dir),
                    config=dict(config or {}),
                    created_ts=created_ts,
                )
            except sqlite3.IntegrityError as exc:
                if run_id_hint:
                    _logger.warning(
                        "job: run_id hint collision on insert run_id=%s err=%s",
                        run_id,
                        exc,
                    )
                    self._debug(
                        f"start_job IntegrityError on explicit hint run_id={run_id}, refusing",
                        run_debug,
                    )
                    raise RuntimeError(f"Le run_id demande est deja utilise : {run_id}") from exc
                _logger.warning(
                    "job: run_id collision on insert, regenerating run_id=%s err=%s",
                    run_id,
                    exc,
                )
                self._debug(
                    f"start_job IntegrityError collision run_id={run_id}, regenerating",
                    run_debug,
                )
                run_id = self._run_id_de_remplacement()
                try:
                    self._store.run.insert_run_pending(
                        run_id=run_id,
                        root=str(root),
                        state_dir=str(state_dir),
                        config=dict(config or {}),
                        created_ts=created_ts,
                    )
                except sqlite3.IntegrityError as exc2:
                    # Si meme l'uuid-style se collide, il y a un probleme grave
                    # (DB corrompue ?). On laisse remonter pour que le caller voie.
                    _logger.error(
                        "job: run_id collision still happening after regen run_id=%s err=%s",
                        run_id,
                        exc2,
                    )
                    raise
            self._debug(f"start_job insert_run_pending OK run_id={run_id}", run_debug)

            snapshot = RunSnapshot(
                run_id=run_id,
                status=RunStatus.PENDING,
                created_ts=created_ts,
                started_ts=None,
                ended_ts=None,
                cancel_requested=False,
                running=True,
                done=False,
                error=None,
            )
            rt = _RuntimeRun(
                run_id=run_id,
                cancel_event=threading.Event(),
                thread=None,
                snapshot=snapshot,
                debug_log=run_debug,
                pause_event=threading.Event(),
            )
            self._runs[run_id] = rt
            self._active_run_id = run_id

            t = threading.Thread(target=self._run_worker, args=(run_id, job_fn), daemon=True)
            rt.thread = t
            t.start()
            _logger.info("job: demarrage thread run_id=%s", run_id)
            self._debug(f"start_job thread start OK run_id={run_id} thread_ident={t.ident}", run_debug)

        return run_id

    def _run_worker(self, run_id: str, job_fn: JobFn) -> None:
        """Boucle de vie complète d'un run : RUNNING -> DONE/CANCELLED/FAILED.

        Position le `run_id` dans le ContextVar de log, exécute `job_fn`, persiste
        le statut final, écrit un crash report en cas d'exception, puis nettoie.
        """
        started_ts = time.time()
        stats: Optional[Dict[str, Any]] = None
        error_message: Optional[str] = None
        run_debug: Optional[Callable[[str], None]] = None

        # V3-04 polish v7.7.0 (R4-LOG-1) : positionner le run_id dans le
        # ContextVar pour que TOUS les logs emis depuis ce thread (et ses
        # appels descendants) soient enrichis avec [run=...]. Le clear est
        # garanti par le finally en bas du try.
        set_run_id(run_id)

        try:
            with self._lock:
                rt = self._runs.get(run_id)
                if not rt:
                    return
                run_debug = rt.debug_log
                self._debug(f"worker entered run_id={run_id}", run_debug)
                cancelled_before_run = rt.cancel_event.is_set()

            if cancelled_before_run:
                self._debug(f"worker cancel before run run_id={run_id}", run_debug)
                # C2 fix (hotfix2) : un run annule AVANT que le worker n'ait pu
                # appeler `mark_run_running` etait persiste CANCELLED avec
                # started_ts=NULL et ended_ts=now(), ce qui violait l'invariant
                # metier "un run cancelled a forcement demarre" (utilise par les
                # rapports, le dashboard, et la duree affichee). On force
                # started_ts = ended_ts = now() ce qui donne une duree de 0s
                # documentee, semantique correcte sans casser l'API ou le schema.
                ended_ts = time.time()
                self._store.run.mark_run_running(run_id, started_ts=ended_ts)
                self._store.run.mark_run_cancelled(run_id, ended_ts=ended_ts)
                with self._lock:
                    self._set_snapshot(
                        run_id,
                        status=RunStatus.CANCELLED,
                        started_ts=ended_ts,
                        ended_ts=ended_ts,
                        cancel_requested=True,
                        running=False,
                        done=True,
                        error=None,
                    )
                return

            self._store.run.mark_run_running(run_id, started_ts=started_ts)
            self._debug(f"worker mark_run_running OK run_id={run_id}", run_debug)
            with self._lock:
                self._set_snapshot(
                    run_id,
                    status=RunStatus.RUNNING,
                    started_ts=started_ts,
                    running=True,
                    done=False,
                    error=None,
                )

            should_cancel = self._should_cancel_factory(run_id)
            should_pause = self._should_pause_factory(run_id)
            self._debug(f"worker calling job_fn run_id={run_id}", run_debug)
            # VN-E.3 : backward compat — on inspecte la signature du job_fn
            # pour passer should_pause si le job_fn l'accepte (kwarg explicite
            # ou **kwargs). Sinon comportement actuel inchange (1 arg positionnel
            # should_cancel uniquement) pour ne pas casser les job_fn legacy.
            # UNE CONNEXION POUR TOUT LE RUN, PAS UNE PAR REQUETE DE REPOSITORY.
            #
            # C'est ICI que vivent les 60 003 connexions d'un scan a froid de
            # 10 000 films, dont l'ouverture pese 23 % du temps total : le job ne
            # passe PAS par le dispatch REST, donc la portee posee la (#1057) ne
            # le couvrait pas.
            #
            # LA CONNEXION VIT DES MINUTES, ET C'EST LE POINT DELICAT. Elle ne
            # tient AUCUNE transaction entre deux appels — chaque `_managed_conn`
            # garde son propre `with conn:` et commite son unite — donc elle ne
            # bloque ni lecteur ni ecrivain. Ce qu'elle tient, c'est un HANDLE de
            # fichier : sous Windows, cela empeche de SUPPRIMER la base. Les deux
            # routes destructives refusent deja tant qu'un run tourne
            # (`_refus_si_run_actif`), et c'est ce garde qui rend cette portee
            # sure — pas une propriete de SQLite.
            with portee_de_requete():
                stats = self._safe_stats(self._invoke_job_fn(job_fn, should_cancel, should_pause))
            self._debug(f"worker job_fn returned run_id={run_id} stats_keys={list((stats or {}).keys())}", run_debug)

            ended_ts = time.time()
            # C4 fix (hotfix2) : avant toute transition terminale, on verifie
            # que le run n'a pas ete pose en PAUSED / SAVED / AWAITING_VALIDATION
            # par l'API entre temps. Sans ce guard, `mark_run_done/cancelled`
            # ecrasait silencieusement l'etat operateur (le UPDATE repo n'a pas
            # de clause WHERE status pour des raisons de backward compat).
            #
            # STATE-MACHINE-001 fix : la cancellation operateur explicite
            # (request_cancel) DOIT prevaloir sur l'etat user-held. Sans cette
            # exception, annuler un run paused laissait le run bloque en
            # PAUSED a vie (slot actif jamais libere par le finally). On passe
            # should_cancel au helper pour qu'il fasse le bypass.
            skip_terminal, db_status_before = self._should_skip_terminal(run_id, should_cancel_fn=should_cancel)
            if skip_terminal:
                self._debug(
                    f"worker terminal transition SKIPPED — db_status={db_status_before} run_id={run_id}",
                    run_debug,
                )
                _logger.info(
                    "job: terminal transition skipped (user-held state) run_id=%s db_status=%s",
                    run_id,
                    db_status_before,
                )
                # On aligne le snapshot memoire sur la DB pour eviter la desync.
                with self._lock:
                    rt_now = self._runs.get(run_id)
                    if rt_now and rt_now.snapshot.status not in _TERMINAL:
                        try:
                            held = RunStatus(db_status_before)
                            self._set_snapshot(
                                run_id,
                                status=held,
                                running=False,
                                done=False,
                            )
                        except (KeyError, OSError, TypeError, ValueError):
                            # Defensif : statut DB inattendu, on n'ecrase pas
                            # le snapshot pour ne pas casser get_status.
                            pass
                return
            if should_cancel():
                self._store.run.mark_run_cancelled(run_id, stats=stats, ended_ts=ended_ts)
                self._debug(f"worker mark_run_cancelled OK run_id={run_id}", run_debug)
                with self._lock:
                    self._set_snapshot(
                        run_id,
                        status=RunStatus.CANCELLED,
                        ended_ts=ended_ts,
                        cancel_requested=True,
                        running=False,
                        done=True,
                        error=None,
                    )
            else:
                self._store.run.mark_run_done(run_id, stats=stats, ended_ts=ended_ts)
                _logger.info("job: termine run_id=%s en %.1fs", run_id, ended_ts - started_ts)
                self._debug(f"worker mark_run_done OK run_id={run_id}", run_debug)
                with self._lock:
                    self._set_snapshot(
                        run_id,
                        status=RunStatus.DONE,
                        ended_ts=ended_ts,
                        running=False,
                        done=True,
                        error=None,
                    )

        # except Exception intentionnel : boundary top-level
        except Exception as exc:
            error_message = str(exc)
            tb_text = traceback.format_exc()
            _logger.error("job: echec run_id=%s: %s", run_id, error_message)
            self._debug(f"worker exception run_id={run_id}: {error_message}\n{tb_text}", run_debug)
            ended_ts = time.time()
            self._write_crash_for_run(run_id, "job_runner worker failed", tb_text)

            # C4 fix (hotfix2) : meme guard que pour DONE/CANCELLED — un
            # crash worker ne doit pas ecraser un PAUSED persiste par l'API.
            # L'erreur reste tracee dans la table `errors` (insert_error).
            #
            # STATE-MACHINE-001 fix : meme exception que dans le try — si
            # l'operateur a demande l'annulation, on laisse le worker faire
            # la transition (ici FAILED si erreur, sinon le bloc try aurait
            # gere CANCELLED). On consulte le cancel_event directement via
            # rt.cancel_event pour ne pas depender d'une closure should_cancel
            # capturee plus haut (qui peut ne pas exister si l'exception a ete
            # levee avant `should_cancel = self._should_cancel_factory(...)`).
            def _cancel_check() -> bool:
                with self._lock:
                    rt_chk = self._runs.get(run_id)
                    if not rt_chk:
                        return False
                    return rt_chk.cancel_event.is_set()

            skip_terminal, db_status_before = self._should_skip_terminal(run_id, should_cancel_fn=_cancel_check)
            if skip_terminal:
                self._debug(
                    f"worker FAILED transition SKIPPED — db_status={db_status_before} run_id={run_id}",
                    run_debug,
                )
                _logger.warning(
                    "job: FAILED transition skipped (user-held state) run_id=%s db_status=%s err=%s",
                    run_id,
                    db_status_before,
                    error_message,
                )
                # On trace tout de meme l'erreur pour ne pas la perdre.
                try:
                    self._store.run.insert_error(
                        run_id=run_id,
                        step="job_runner",
                        code=exc.__class__.__name__,
                        message=error_message,
                        context={"run_id": run_id, "traceback": tb_text, "skipped_terminal": db_status_before},
                    )
                # except Exception : ne pas masquer la propagation finally
                except Exception as exc2:
                    self._debug(f"worker insert_error failure run_id={run_id}: {exc2}", run_debug)
            else:
                self._store.run.mark_run_failed(run_id, error_message=error_message, ended_ts=ended_ts)
                self._store.run.insert_error(
                    run_id=run_id,
                    step="job_runner",
                    code=exc.__class__.__name__,
                    message=error_message,
                    context={"run_id": run_id, "traceback": tb_text},
                )
                with self._lock:
                    self._set_snapshot(
                        run_id,
                        status=RunStatus.FAILED,
                        ended_ts=ended_ts,
                        running=False,
                        done=True,
                        error=error_message,
                    )
        finally:
            # Issue #515 : AVANT toute autre chose, garantir que le run a quitte
            # RUNNING — y compris quand c'est le gestionnaire d'echec lui-meme
            # qui a leve et que l'exception secondaire est en train de se
            # propager a travers ce `finally`.
            try:
                self._ensure_run_left_running(run_id, error_message=error_message, run_debug=run_debug)
            # except Exception : une exception levee ICI remplacerait celle qui
            # est en cours de propagation — le diagnostic d'origine (la panne DB)
            # serait perdu au profit d'un defaut du filet lui-meme, et la suite
            # du `finally` (liberation du slot actif, ContextVar) serait sautee.
            except Exception as exc:
                _logger.exception("job: filet de securite en echec run_id=%s: %s", run_id, exc)
            with self._lock:
                rt = self._runs.get(run_id)
                # H15 fix (hotfix2) : ne pas liberer le slot actif si le run
                # est en etat sous controle operateur (PAUSED/SAVED/AWAITING).
                # Sinon `start_job` autoriserait un second run en parallele
                # alors qu'un run est en attente d'action utilisateur.
                #
                # HOTFIX3 fallback : si le snapshot est reste sur RUNNING
                # (ou un etat non-terminal et non-reserved) apres sortie du
                # `try` — typiquement parce que le guard C4 a leve une
                # exception apres avoir lu db_status_before mais avant
                # d'aligner le snapshot —, on tente un dernier alignement
                # via la DB pour ne pas laisser snapshot=RUNNING en perma
                # et eviter de liberer le slot a tort.
                if rt and self._active_run_id == run_id:
                    held = rt.snapshot.status in (
                        RunStatus.PAUSED,
                        RunStatus.SAVED,
                        RunStatus.AWAITING_VALIDATION,
                    )
                    if not held and rt.snapshot.status not in _TERMINAL:
                        db_status_final = self._current_db_status(run_id)
                        if self._is_user_held_state(db_status_final):
                            try:
                                held_status = RunStatus(db_status_final)
                                self._set_snapshot(
                                    run_id,
                                    status=held_status,
                                    running=False,
                                    done=False,
                                )
                                held = True
                                self._debug(
                                    f"worker finally aligned snapshot on DB={db_status_final} run_id={run_id}",
                                    run_debug,
                                )
                            except (KeyError, OSError, TypeError, ValueError):
                                # Defensif : si le mapping echoue, on conserve
                                # held=True base sur la DB pour ne pas liberer
                                # le slot a tort tant que la DB indique un
                                # etat user-held.
                                held = True
                    if not held:
                        self._active_run_id = None

                rt_after = self._runs.get(run_id)
                if rt_after and rt_after.snapshot.status in _TERMINAL and rt_after.snapshot.ended_ts is None:
                    self._set_snapshot(
                        run_id,
                        ended_ts=time.time(),
                        running=False,
                        done=True,
                        error=error_message
                        if rt_after.snapshot.status == RunStatus.FAILED
                        else rt_after.snapshot.error,
                    )

                # Nettoyer les runs termines anciens pour eviter la fuite memoire (H6)
                # On garde les 5 derniers runs termines pour consultation.
                if len(self._runs) > 5:
                    finished = [(k, v) for k, v in self._runs.items() if v.snapshot.status in _TERMINAL]
                    finished.sort(key=lambda kv: kv[1].snapshot.started_ts or 0.0)
                    # On supprime les plus anciens, en gardant les 5 derniers termines
                    to_drop = finished[:-5] if len(finished) > 5 else []
                    for key, _rt in to_drop:
                        self._runs.pop(key, None)
            self._debug(f"worker finally released active_run run_id={run_id}", run_debug)
            # V3-04 polish v7.7.0 : effacer le run_id du ContextVar pour que les
            # logs emis hors-job (timers daemon) ne portent pas un run_id obsolete.
            clear_run_id()

    def request_cancel(self, run_id: str) -> bool:
        """Demande l'annulation d'un run actif. Renvoie False si inconnu/déjà terminé."""
        run_debug: Optional[Callable[[str], None]] = None
        with self._lock:
            rt = self._runs.get(run_id)
            if not rt:
                self._debug(f"request_cancel ignored: unknown run_id={run_id}", run_debug)
                return False
            run_debug = rt.debug_log
            if rt.snapshot.status in _TERMINAL:
                self._debug(
                    f"request_cancel ignored: run_id={run_id} already terminal={rt.snapshot.status.value}", run_debug
                )
                return False
            rt.cancel_event.set()
            self._set_snapshot(run_id, cancel_requested=True)
            # H16 fix (hotfix2) : si le run est PAUSED, le worker est endormi
            # dans `wait_while_paused()` (ou equivalent) et n'observera jamais
            # `cancel_requested` tant que `pause_event` est pose. On efface
            # `pause_event` APRES avoir pose `cancel_event` pour debloquer la
            # boucle cooperative — l'ordre est important : `should_cancel`
            # doit voir True avant que le worker ne reprenne sa boucle, sinon
            # il interpreterait le clear comme un resume.
            if rt.pause_event is not None and rt.pause_event.is_set():
                rt.pause_event.clear()
                self._debug(f"request_cancel cleared pause_event for PAUSED run_id={run_id}", run_debug)
            self._debug(f"request_cancel set cancel flag run_id={run_id}", run_debug)

        self._store.run.mark_cancel_requested(run_id)
        self._debug(f"request_cancel persisted cancel_requested run_id={run_id}", run_debug)
        return True

    def request_pause(self, run_id: str, *, saved: bool = False) -> bool:
        """Demande la suspension d'un run actif. Pose le `pause_event`.

        V8-01 spec 08 Traitement : la pause est cooperative — le job_fn doit
        verifier `_should_pause()` (via le factory ci-dessous) dans sa boucle
        pour suspendre proprement. Retourne False si run inconnu ou deja
        termine. Pas de persistance ici : le caller (RunControlSupport) gere
        l'etat DB via `RunRepository.mark_run_paused`.

        C3 fix (hotfix2) : aligne aussi le snapshot memoire sur PAUSED pour
        eviter la desync entre l'etat DB (PAUSED) et l'etat memoire (RUNNING).
        `_active_run_locked`, `get_status` et `_run_worker` lisent tous le
        snapshot ; sans cette mise a jour, l'UI affichait toujours RUNNING.

        HOTFIX3 fix : ajout du parametre keyword-only `saved` pour permettre
        au caller (RunControlSupport.save_for_later) de demander un alignement
        snapshot=SAVED au lieu de PAUSED. Le fix C3 d'origine forcait
        inconditionnellement snapshot=PAUSED, ce qui re-introduisait la desync
        snapshot=PAUSED / DB=SAVED lorsque le caller faisait
        `mark_run_paused(saved=True)`. Le defaut `saved=False` preserve la
        backward compat des callers existants (tests, autres call sites).
        """
        run_debug: Optional[Callable[[str], None]] = None
        target_status = RunStatus.SAVED if saved else RunStatus.PAUSED
        with self._lock:
            rt = self._runs.get(run_id)
            if not rt:
                self._debug(f"request_pause ignored: unknown run_id={run_id}", run_debug)
                return False
            run_debug = rt.debug_log
            if rt.snapshot.status in _TERMINAL:
                self._debug(f"request_pause ignored: run_id={run_id} terminal={rt.snapshot.status.value}", run_debug)
                return False
            if rt.pause_event is None:
                rt.pause_event = threading.Event()
            rt.pause_event.set()
            # C3 + HOTFIX3 : aligne le snapshot memoire sur le target choisi
            # par le caller (PAUSED par defaut, SAVED si save_for_later).
            # Idempotent si snapshot est deja sur le bon target.
            if rt.snapshot.status != target_status:
                self._set_snapshot(run_id, status=target_status, running=False)
            self._debug(f"request_pause set pause flag run_id={run_id} target={target_status.value}", run_debug)
        return True

    def request_resume(self, run_id: str) -> bool:
        """Efface le flag de pause pour permettre la reprise du worker.

        Symetrique de `request_pause`. Retourne False si run inconnu ou
        deja termine. Pas de persistance : caller gere via
        `RunRepository.mark_run_resumed`.

        C3 fix (hotfix2) : restaure aussi le snapshot memoire vers RUNNING
        pour cloturer la desync introduite par `request_pause`.

        HOTFIX3 fix : etend le set de transitions valides PAUSED -> RUNNING
        a SAVED -> RUNNING et AWAITING_VALIDATION -> RUNNING pour rester
        coherent avec `request_pause(saved=True)` et avec
        `RunRepository.mark_run_resumed` qui autorise SAVED -> RUNNING.
        """
        run_debug: Optional[Callable[[str], None]] = None
        resumable = (RunStatus.PAUSED, RunStatus.SAVED, RunStatus.AWAITING_VALIDATION)
        with self._lock:
            rt = self._runs.get(run_id)
            if not rt:
                self._debug(f"request_resume ignored: unknown run_id={run_id}", run_debug)
                return False
            run_debug = rt.debug_log
            if rt.snapshot.status in _TERMINAL:
                self._debug(f"request_resume ignored: run_id={run_id} terminal={rt.snapshot.status.value}", run_debug)
                return False
            if rt.pause_event is not None:
                rt.pause_event.clear()
            # C3 + HOTFIX3 : restaure le snapshot memoire vers RUNNING si on
            # etait dans un etat suspendu (PAUSED/SAVED/AWAITING_VALIDATION).
            if rt.snapshot.status in resumable:
                self._set_snapshot(run_id, status=RunStatus.RUNNING, running=True)
            self._debug(f"request_resume clear pause flag run_id={run_id}", run_debug)
        return True

    def is_paused(self, run_id: str) -> bool:
        """Indique si le `pause_event` est pose pour ce run.

        Utilisable par le job_fn pour decider de suspendre la boucle. Renvoie
        False pour un run inconnu (defensif : on n'introduit pas de blocage).
        """
        with self._lock:
            rt = self._runs.get(run_id)
            if not rt or rt.pause_event is None:
                return False
            return rt.pause_event.is_set()

    def get_status(self, run_id: str) -> Optional[RunSnapshot]:
        """Renvoie le `RunSnapshot` courant pour ce `run_id` (mémoire puis BDD)."""
        with self._lock:
            rt = self._runs.get(run_id)
            if rt:
                return rt.snapshot

        row = self._store.run.get_run(run_id)
        if not row:
            return None

        try:
            status = RunStatus(str(row.get("status") or "FAILED"))
        except (KeyError, OSError, TypeError, ValueError):
            status = RunStatus.FAILED

        return RunSnapshot(
            run_id=str(row.get("run_id") or run_id),
            status=status,
            created_ts=float(row.get("created_ts") or 0.0),
            started_ts=float(row["started_ts"]) if row.get("started_ts") is not None else None,
            ended_ts=float(row["ended_ts"]) if row.get("ended_ts") is not None else None,
            cancel_requested=bool(row.get("cancel_requested") or 0),
            running=status in _ACTIVE,
            done=status in _TERMINAL,
            error=str(row.get("error_message")) if row.get("error_message") else None,
        )
