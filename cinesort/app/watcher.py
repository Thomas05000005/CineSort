"""Mode planifie / Watch folder — surveillance des roots et scan automatique.

Thread daemon qui poll les dossiers racine toutes les N minutes.
Quand un changement est detecte (nouveau dossier, dossier supprime, mtime modifie),
un scan est declenche automatiquement via start_plan().
"""

from __future__ import annotations

import logging
import os
import stat
import threading
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from cinesort.infra.fs_safety import is_dir_accessible

logger = logging.getLogger("cinesort.watcher")

# Identite PHYSIQUE d'un dossier : (st_dev, st_ino). Deux chemins qui rendent le
# meme couple designent le meme dossier sur le disque, meme si l'un passe par une
# jonction NTFS.
Identite = Tuple[int, int]


def _est_lien(entry: "os.DirEntry[str]") -> bool:
    """True si l'entree redirige ailleurs : jonction NTFS ou lien symbolique.

    Lit les attributs deja rapportes par `scandir` : aucun aller-retour disque,
    ce qui compte sur un partage SMB.

    `is_junction()` existe depuis Python 3.12 ; le `getattr` evite de faire
    tomber le watcher sur un interpreteur plus ancien. En cas d'echec de
    lecture on repond True, parce que c'est le sens qui CONTINUE de surveiller
    correctement : la branche « lien » relit la cible avec `os.stat`, alors que
    repondre False ferait retomber sur le mtime du lien lui-meme, lequel ne
    bouge jamais quand la cible change (c'est l'angle mort corrige ici).
    """
    try:
        if entry.is_symlink():
            return True
    except OSError:
        return True
    est_jonction = getattr(entry, "is_junction", None)
    if est_jonction is None:  # pragma: no cover - Python < 3.12
        return False
    try:
        return bool(est_jonction())
    except OSError:
        return True


def _stat_cible(chemin: str) -> Optional[os.stat_result]:
    """`os.stat` de la CIBLE (les liens sont suivis), ou None si illisible."""
    try:
        return os.stat(chemin)
    except (OSError, ValueError):
        return None


def _identite_physique(st: Optional[os.stat_result]) -> Optional[Identite]:
    """(st_dev, st_ino) du dossier vise, ou None si l'identite ne dit rien.

    `st_ino` vaut 0 sur les systemes de fichiers qui ne le renseignent pas :
    le couple ne distinguerait alors plus rien et deviendrait un faux « deja
    vu » qui ferait disparaitre des dossiers legitimes du snapshot.
    """
    if st is None:
        return None
    ino = int(getattr(st, "st_ino", 0) or 0)
    if not ino:
        return None
    return (int(getattr(st, "st_dev", 0) or 0), ino)


def _snapshot_root(root: Path) -> FrozenSet[str]:
    """Snapshot leger d'un root : liste des dossiers de niveau 1 avec mtime.

    Ignore les dossiers commencant par '_' (buckets internes CineSort).
    Retourne un frozenset de 'nom|mtime_ns'.

    Issue #614 — jonctions NTFS et liens de dossier. Trois faits mesures sur
    Windows 11 / CPython 3.13, avec une VRAIE jonction (`mklink /J`) et un vrai
    lien symbolique de dossier (`mklink /D`) :

      * jonction : `is_dir(follow_symlinks=False)` rend **True** — elle etait
        donc bien dans le snapshot, contrairement a ce qu'annonce l'issue. Mais
        `entry.stat()` rend les attributs du LIEN, dont le mtime ne bouge JAMAIS
        quand la cible change (releve a t+0, +1, +3 et +6 s apres creation d'un
        dossier dans la cible : valeur du cache inchangee, `os.stat` change des
        t+0). La branche attachee etait surveillee en apparence, muette en fait.
      * lien /D : `is_dir(follow_symlinks=False)` rend **False** — purement
        absent du snapshot, jamais surveille.
      * les deux : `os.stat` rend le meme `(st_dev, st_ino)` que la cible. C'est
        l'identite physique, et donc le seul moyen de voir la DUPLICATION : un
        meme dossier atteint par deux chemins etait compte deux fois, ce qui
        gonflait le message de changement envoye en notification (« +2 » pour un
        seul dossier ajoute) et doublait le travail de chaque poll.

    Le watcher ne renonce jamais a surveiller : une identite illisible fait
    GARDER l'entree, et un lien dont la cible est momentanement injoignable y
    reste aussi — l'en retirer ferait croire a une suppression et declencherait
    un scan automatique pour rien (meme faux positif que celui traite par
    R5-CRIT-6 dans `_trigger_scan`).
    """
    reels: List[Tuple[str, str, int]] = []  # (nom, chemin, mtime rendu par scandir)
    liens: List[Tuple[str, str]] = []  # (nom, chemin)
    try:
        with os.scandir(root) as scanner:
            for entry in scanner:
                nom = entry.name
                if nom.startswith("_"):
                    continue
                if _est_lien(entry):
                    liens.append((nom, entry.path))
                    continue
                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                try:
                    reels.append((nom, entry.path, int(entry.stat().st_mtime_ns)))
                except (OSError, ValueError):
                    reels.append((nom, entry.path, 0))
    except OSError:
        # `FileNotFoundError` et `PermissionError` sont des `OSError`. On rend le
        # snapshot partiel deja constitue, comme avant.
        pass

    if not liens:
        # Aucun lien : aucune duplication possible. Deux entrees distinctes d'un
        # meme dossier ne peuvent designer le meme dossier physique sans point
        # d'analyse — NTFS n'a pas de lien dur de dossier. On garde donc le
        # chemin rapide historique, sans aucun `os.stat` supplementaire : mesure
        # locale sur 300 dossiers, 1,2 ms via le cache de `scandir` contre
        # 16,7 ms via `os.stat`, soit x14. Le mtime du cache peut retarder d'une
        # seconde environ (mesure), ce qui est sans effet a un intervalle de
        # poll d'au moins 60 s.
        return frozenset(f"{nom}|{mtime}" for nom, _chemin, mtime in reels)

    vus: set[Identite] = set()
    # Graine : le root lui-meme. Une jonction qui pointe sur son propre parent
    # (`Films/Raccourci -> Films`) compterait sinon le root comme l'un de ses
    # propres enfants.
    identite_root = _identite_physique(_stat_cible(str(root)))
    if identite_root is not None:
        vus.add(identite_root)

    entries: set[str] = set()
    # Les dossiers REELS d'abord : ils prennent l'identite, donc c'est leur nom
    # — celui que l'utilisateur reconnait — qui survit quand un lien designe le
    # meme dossier. Aucun dossier reel n'est jamais retire par cette garde.
    for nom, chemin, mtime in reels:
        identite = _identite_physique(_stat_cible(chemin))
        if identite is not None:
            vus.add(identite)
        entries.add(f"{nom}|{mtime}")

    # Puis les liens, tries par nom : `os.scandir` ne garantit aucun ordre, et un
    # choix qui dependrait de cet ordre ferait varier le snapshot d'un poll a
    # l'autre — donc un faux changement, donc un scan automatique pour rien, a
    # chaque intervalle.
    for nom, chemin in sorted(liens):
        st = _stat_cible(chemin)
        if st is None:
            # Cible injoignable (NAS eteint) ou lien casse : on GARDE l'entree.
            entries.add(f"{nom}|0")
            continue
        if not stat.S_ISDIR(st.st_mode):
            continue
        identite = _identite_physique(st)
        if identite is not None:
            if identite in vus:
                logger.debug(
                    "[watcher] %s designe un dossier deja surveille (jonction ou lien), ignore",
                    chemin,
                )
                continue
            vus.add(identite)
        entries.add(f"{nom}|{int(st.st_mtime_ns)}")
    return frozenset(entries)


def _snapshot_all(roots: List[Path]) -> Dict[str, FrozenSet[str]]:
    """Snapshot de tous les roots, un seul par dossier PHYSIQUE.

    Deux roots configures qui designent le meme dossier (l'un via une jonction)
    doublaient le travail de chaque poll et annoncaient deux fois le meme
    changement dans la notification envoyee a l'utilisateur.

    Un root dont l'identite est illisible est conserve : on ne renonce pas a
    surveiller sur un doute.
    """
    snapshots: Dict[str, FrozenSet[str]] = {}
    vus: set[Identite] = set()
    for root in roots:
        cle = str(root)
        if cle in snapshots:
            continue
        identite = _identite_physique(_stat_cible(cle))
        if identite is not None:
            if identite in vus:
                logger.debug(
                    "[watcher] root %s deja surveille par un autre chemin, ignore",
                    cle,
                )
                continue
            vus.add(identite)
        snapshots[cle] = _snapshot_root(root)
    return snapshots


def _has_changed(
    old: Dict[str, FrozenSet[str]],
    new: Dict[str, FrozenSet[str]],
) -> Tuple[bool, str]:
    """Compare deux snapshots. Retourne (changed, detail_message)."""
    if old == new:
        return False, ""
    details: list[str] = []
    all_roots = set(old) | set(new)
    for root in sorted(all_roots):
        old_set = old.get(root, frozenset())
        new_set = new.get(root, frozenset())
        if old_set != new_set:
            old_names = {e.rsplit("|", 1)[0] for e in old_set}
            new_names = {e.rsplit("|", 1)[0] for e in new_set}
            added = new_names - old_names
            removed = old_names - new_names
            modified = len(new_set - old_set) - len(added)
            parts: list[str] = []
            if added:
                parts.append(f"+{len(added)}")
            if removed:
                parts.append(f"-{len(removed)}")
            if modified > 0:
                parts.append(f"~{modified}")
            details.append(f"{root} ({', '.join(parts) or 'change'})")
    return True, "; ".join(details)


class FolderWatcher(threading.Thread):
    """Thread daemon de surveillance des dossiers racine."""

    def __init__(
        self,
        api: Any,
        *,
        interval_s: float = 300.0,
        roots: Optional[List[Path]] = None,
    ) -> None:
        super().__init__(name="cinesort-watcher", daemon=True)
        self._api = api
        self._interval_s = max(10.0, float(interval_s))
        self._roots = list(roots) if roots else []
        self._stop_event = threading.Event()
        self._previous_snapshot: Dict[str, FrozenSet[str]] = {}

    @property
    def is_active(self) -> bool:
        """True si le thread tourne et n'est pas en cours d'arret."""
        return self.is_alive() and not self._stop_event.is_set()

    def stop(self) -> None:
        """Demande l'arret propre du thread."""
        self._stop_event.set()
        self.join(timeout=5)
        logger.info("[watcher] stopped")

    def run(self) -> None:
        """Boucle principale : snapshot initial puis poll periodique."""
        logger.info(
            "[watcher] started, interval=%ds, roots=%s",
            int(self._interval_s),
            [str(r) for r in self._roots],
        )

        # Snapshot initial — pas de scan au premier poll
        self._previous_snapshot = _snapshot_all(self._roots)
        logger.debug("[watcher] initial snapshot: %d root(s)", len(self._previous_snapshot))

        while not self._stop_event.is_set():
            # Attendre l'intervalle (interruptible par stop)
            if self._stop_event.wait(timeout=self._interval_s):
                break  # stop() a ete appele

            if self._stop_event.is_set():
                break

            # Nouveau snapshot
            current = _snapshot_all(self._roots)
            changed, detail = _has_changed(self._previous_snapshot, current)

            if not changed:
                logger.debug("[watcher] poll: no change")
                continue

            logger.info("[watcher] change detected: %s", detail)

            # Verifier qu'aucun scan n'est en cours AVANT de remplacer le
            # snapshot baseline. Sinon le changement detecte ici (A -> B)
            # serait perdu : on aurait deja remplace par B, et au prochain
            # poll _has_changed(B, B) renverrait False alors qu'aucun scan
            # n'a ete declenche pour ce changement.
            if self._is_scan_running():
                logger.info("[watcher] scan skipped (already running), change kept for next poll")
                continue

            # Le scan va etre declenche : on peut maintenant graver le snapshot.
            self._previous_snapshot = current

            # Declencher le scan
            self._trigger_scan(detail)

    def _is_scan_running(self) -> bool:
        """Verifie si un scan est deja en cours via l'API."""
        runs = getattr(self._api, "_runs", None)
        runs_lock = getattr(self._api, "_runs_lock", None)
        if not runs or not runs_lock:
            return False
        with runs_lock:
            for rs in runs.values():
                if getattr(rs, "running", False) and not getattr(rs, "done", False):
                    return True
        return False

    def _trigger_scan(self, detail: str) -> None:
        """Lance un scan automatique via start_plan.

        R5-CRIT-6 fix : valide que tous les roots sont accessibles AVANT de lancer
        le scan. Sinon, NAS deconnecte = snapshot vide = "100 dossiers disparus"
        detecte = scan auto declenche pour rien (faux positif).
        """
        # R5-CRIT-6 : pre-validation accessibility roots
        inaccessible: List[str] = []
        for root in self._roots:
            try:
                if not is_dir_accessible(root, timeout_s=5.0):
                    inaccessible.append(str(root))
            except (OSError, ValueError):
                inaccessible.append(str(root))
        if inaccessible:
            logger.warning(
                "[watcher] scan annule, %d root(s) inaccessible(s): %s",
                len(inaccessible),
                ", ".join(inaccessible[:3]),
            )
            return

        try:
            settings = self._api.settings.get_settings()
            logger.info("[watcher] scan triggered")
            result = self._api.run.start_plan(settings)
            if result.get("ok"):
                # Cf issue #108 : notification ENVOYEE APRES start_plan succes
                # avec event "scan_triggered" (et plus "scan_done" qui mentait).
                # Le vrai "scan_done" est envoye par run_flow_support quand le
                # scan termine effectivement.
                self._api._notify.notify(
                    "scan_triggered",
                    "Scan automatique",
                    f"Changement detecte. Scan lance en arriere-plan. ({detail})",
                )
                logger.info("[watcher] scan started run_id=%s", result.get("run_id", "?"))
            else:
                logger.warning("[watcher] scan failed: %s", result.get("message", "?"))
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("[watcher] scan trigger error: %s", exc)
