"""Helpers partages pour la suite de tests CineSort.

Issue #86 PR 2 : module utilitaire commun, utilisable par unittest et pytest.

Le `conftest.py` racine fournit deja les fixtures pytest (`free_port`,
`create_movie_file`, `tmp_state_dir`, `wait_run_terminal`). Ce module
expose les MEMES helpers sous forme de fonctions importables, pour les
tests `unittest.TestCase` qui ne peuvent pas consommer les fixtures pytest
naturellement.

Usage :

    from tests._helpers import find_free_port

    class MyTests(unittest.TestCase):
        def setUp(self):
            self.port = find_free_port()
"""

from __future__ import annotations

import gc
import os
import shutil
import socket
import sqlite3
import tempfile
import threading
import time
import weakref
from pathlib import Path
from typing import Any, Tuple

# Budget par defaut pour attendre la fin des threads de fond de l'app. Mesure :
# les threads `recompute_*` / `tmdb-enrich-*` se terminent en quelques dizaines
# de millisecondes ; 5 s est une borne de securite, jamais atteinte en pratique.
DEFAULT_THREAD_JOIN_TIMEOUT_S = 5.0
# Plafond pour UN thread : un thread inconnu qui ne se terminerait jamais coute
# ce montant une fois, au lieu d'avaler tout le budget de la fonction.
MAX_SINGLE_THREAD_JOIN_S = 2.0

#: Threads qui ont deja epuise leur budget de join sans se terminer. Ils ne
#: sont plus attendus : la deuxieme attente a exactement le meme resultat que la
#: premiere, pour le meme prix.
#:
#: MESURE : `tests/test_fs_safety.py` abandonne 3 threads anonymes (`Thread-N`)
#: dans `fs_safety.run_with_timeout` — ils ne portent pas de nom de service,
#: donc `is_service_thread` ne peut rien pour eux, et ils restent vivants
#: pendant 221 tests. Sans cette memoire, chaque `cleanup_test_tree` de cette
#: fenetre payait le budget ENTIER (3 x 2 s, plafonne a 5 s) pour rien.
#:
#: `WeakSet` et non un ensemble d'`ident` : un `ident` est recycle par l'OS
#: apres la mort du thread, ce qui ferait sauter a tort l'attente d'un NOUVEAU
#: thread. L'identite de l'objet, elle, ne se recycle pas, et la reference
#: faible n'empeche pas le ramasse-miettes de faire son travail.
_INSENSIBLES: "weakref.WeakSet[threading.Thread]" = weakref.WeakSet()


def _budget(local_s: float) -> float:
    """Budget d'attente, elargi sur un runner de CI.

    Les runners GitHub sont sensiblement plus lents que la machine de dev, et
    surtout leur latence est TRES variable selon la charge du parc. Mesure du
    2026-08-03 : `tests/test_apply_preview.py` construit son plan en ~5 s en
    local et a mis **11 s** sur un runner — au-dela du budget de 10 s — alors
    que le journal du run montrait `PLAN READY` atteint, donc aucun blocage
    reel. Deux tests tombaient au hasard, et un check requis rouge suffit a
    empecher toute fusion.

    On ne releve pas le budget local : c'est lui qui attrape les vrais
    interblocages en developpement, et l'allonger reviendrait a attendre une
    minute pour apprendre qu'on s'est bloque. Seule la CI, ou le budget mesure
    autre chose (la charge du parc), est elargie.

    `CINESORT_TEST_TIMEOUT_S` permet de forcer une valeur, utile pour
    reproduire un timeout en local sans toucher au code.
    """
    forced = os.environ.get("CINESORT_TEST_TIMEOUT_S")
    if forced:
        try:
            return float(forced)
        except ValueError:
            pass
    return local_s * 3.0 if os.environ.get("CI") else local_s


#: Prefixe de nom porte par TOUS les services de l'app, et par eux seuls.
#: Verifie sur les 11 sites de creation de threads de `cinesort/` :
#:   services  -> `cinesort-watcher`, `cinesort-quarantine-ttl`,
#:                `cinesort-retention-cleanup`, `cinesort-rest-api` ;
#:   travailleurs -> `recompute_*`, `tmdb-enrich-*`, `perc-*`, `perc-batch-*`,
#:                `email-*`, `plugin-hook-*`, et les `Thread-N` anonymes de
#:                `job_runner` / `fs_safety`.
_SERVICE_NAME_PREFIX = "cinesort-"


def is_service_thread(thread: threading.Thread) -> bool:
    """True si le thread est un SERVICE qui ne se terminera pas tout seul.

    Deux regles, parce qu'une seule ne couvrait qu'un service sur quatre.

    1. **Par capacite** : un thread qui expose lui-meme un evenement d'arret
       (`_stop_event`) attend qu'on le lui demande. Cette regle n'est
       satisfaisable que par une SOUS-CLASSE de `Thread` — donc, dans ce depot,
       par le seul `FolderWatcher`.
    2. **Par nom** : les trois autres services sont construits par
       `threading.Thread(target=_worker, name="cinesort-...")` et posent leur
       evenement d'arret sur l'objet `api`, pas sur le thread — la regle 1 ne
       peut structurellement pas les voir. Ils partagent en revanche un prefixe
       de nom que ne porte aucun travailleur (cf. `_SERVICE_NAME_PREFIX`).

    MESURE qui a impose la regle 2 : avec la seule regle 1,
    `join_background_threads(5.0)` coutait **4,02 s et laissait les deux crons
    vivants**. En suite complete, `cinesort-quarantine-ttl` demarre dans
    `tests/test_quarantaine_ttl_v77.py` et reste vivant jusqu'au DERNIER test de
    la session — soit 2 087 tests, dont 58 appellent `cleanup_test_tree`.

    MESURE initiale, conservee : le thread `cinesort-watcher` (poll toutes les
    300 s) a produit **107 joins de 5 s, soit 535 s** sur une execution. Les
    threads de travail, eux, se terminent : 37 joins de `recompute_*` pour 7,5 s
    au total. On saute donc les services, et on attend les travailleurs.
    """
    if isinstance(getattr(thread, "_stop_event", None), threading.Event):
        return True
    return str(getattr(thread, "name", "") or "").startswith(_SERVICE_NAME_PREFIX)


def join_background_threads(
    timeout_s: float = DEFAULT_THREAD_JOIN_TIMEOUT_S,
    *,
    per_thread_s: float = MAX_SINGLE_THREAD_JOIN_S,
) -> list[str]:
    """Attend la fin des threads de fond demarres par l'app. Retourne leurs noms.

    Pourquoi (issue #960, MESURE) : les facades `api.run.*` demarrent des
    threads DAEMON (`recompute_*`, `tmdb-enrich-*`) qui survivent a la fin du
    test. Ils continuent d'ecrire dans le `state_dir` du test — au point de
    RECREER l'arborescence juste apres que le `tearDown` l'a supprimee. Mesure
    sur `tests/test_api_bridge_lot3.py` : 13 dossiers laisses dans %TEMP%, dont
    12 recrees APRES une suppression pourtant reussie. Un `rmtree` seul ne peut
    donc pas gagner cette course.

    C'est aussi la source la plus vraisemblable des `PermissionError
    [WinError 5/32]` attribues au « verrou de fichiers Windows » : le thread
    d'un test tombe sur le dossier d'un test VOISIN en train d'etre renomme.

    Ne joint jamais le thread principal, le thread courant, ni un thread de
    service (cf. `is_service_thread`). Deux plafonds : `timeout_s` pour le total
    et `per_thread_s` pour un seul thread — ainsi un thread inconnu qui ne
    finirait jamais coute une fois `per_thread_s`, pas tout le budget.

    Un thread qui a deja survecu a un join complet n'est plus jamais attendu
    (cf. `_INSENSIBLES`) : le payer une fois est une precaution, le payer a
    chaque appel est une taxe.
    """
    deadline = time.monotonic() + float(timeout_s)
    current = threading.current_thread()
    main = threading.main_thread()
    joined: list[str] = []
    for thread in threading.enumerate():
        if thread is current or thread is main or not thread.is_alive():
            continue
        if is_service_thread(thread) or thread in _INSENSIBLES:
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        budget = min(remaining, float(per_thread_s))
        thread.join(budget)
        joined.append(thread.name)
        # Il a consomme tout son budget sans finir : il ne finira pas non plus
        # au prochain appel. On cesse de le payer.
        if thread.is_alive():
            _INSENSIBLES.add(thread)
    return joined


def cleanup_test_tree(
    path: str | Path,
    *,
    timeout_s: float = DEFAULT_THREAD_JOIN_TIMEOUT_S,
    attempts: int = 4,
) -> bool:
    """Supprime un arbre temporaire de test, sans laisser de reste dans %TEMP%.

    Trois etapes, chacune motivee par une mesure :
      1. joindre les threads de fond, sinon ils recreent l'arborescence ;
      2. `rmtree` ;
      3. s'il reste quelque chose : `gc.collect()` puis nouvelle tentative. Une
         exception gardee vivante par un mock retient son traceback, donc des
         frames, donc des connexions sqlite3 et des fichiers d'audit ouverts —
         des cycles que seul le ramasse-miettes casse (WinError 32 sinon). Et
         un handle peut etre relache quelques dizaines de ms plus tard.

    Le `gc.collect()` est volontairement APRES la premiere tentative et non
    avant : MESURE, il coute ~0,4 s sur le tas d'une session complete, et le
    payer a chaque `tearDown` ajoutait ~9 minutes a la suite. Le chemin
    nominal — la suppression reussit du premier coup — ne le paie plus.

    Retourne True si le dossier a disparu. A utiliser dans les fichiers qui
    pilotent l'API. Pour un test qui ne cree qu'un dossier inerte,
    `self.addCleanup(shutil.rmtree, d, ignore_errors=True)` suffit et coute
    moins cher.
    """
    target = str(path)
    join_background_threads(timeout_s)
    for attempt in range(max(1, attempts)):
        shutil.rmtree(target, ignore_errors=True)
        if not os.path.exists(target):
            return True
        gc.collect()
        time.sleep(0.05 * (attempt + 1))
    shutil.rmtree(target, ignore_errors=True)
    return not os.path.exists(target)


def find_free_port() -> int:
    """Retourne un port TCP libre sur 127.0.0.1.

    Remplace les 14 definitions duplicatees de `_find_free_port` dans
    les fichiers de test (issue #86).

    NB : il y a une race condition entre l'obtention du port et son
    utilisation. Acceptable pour les serveurs longs-running du test
    (REST server, etc.), risque negligeable.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def create_file(path: Path, size: int = 2048) -> None:
    """Cree un fichier video minimal de taille `size` bytes.

    Remplace les 8+ definitions duplicatees de `_create_file` dans les
    fichiers de test (issue #86). Cree les parents manquants automatiquement.

    Defaut size=2048 bytes (> MIN_VIDEO_BYTES dans la plupart des configs).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def wait_run_done(api: Any, run_id: str, timeout_s: float | None = None) -> dict:
    """Poll `api.run.get_status(run_id)` jusqu'a etat terminal (done=True).

    Remplace les 10+ definitions duplicatees de `_wait_done` /
    `_wait_terminal` dans les fichiers de test (issue #86).

    - Retourne le dernier status (dict avec done=True)
    - Raise AssertionError si timeout (compatible avec unittest self.fail
      qui wrappe AssertionError)
    - Poll 30 ms (compromis entre charge CPU et reactivite)

    Si le caller ignore le return (pattern `self._wait_done(api, run_id)`
    sans assignation), c'est OK — la valeur est retournee mais ignoree.
    """
    budget = _budget(10.0 if timeout_s is None else float(timeout_s))
    deadline = time.monotonic() + budget
    last: dict = {}
    while time.monotonic() < deadline:
        last = api.run.get_status(run_id, 0) or {}
        if last.get("done"):
            return last
        time.sleep(0.03)
    raise AssertionError(f"Timeout {budget}s en attendant run_id={run_id}. Dernier status={last}")


def wait_runner_terminal(runner: Any, run_id: str, timeout_s: float | None = None) -> bool:
    """Poll `runner.get_status(run_id)` (JobRunner direct) jusqu'a snapshot.done.

    MEGA-HOTFIX bug (5) : factorisation du pattern `_wait_terminal` duplique
    dans `test_pause_cooperative_v77.py`, `test_apply_atomic_rollback_integration_v77.py`,
    et `test_job_runner_state_machine_v77.py`. Symetrique de `wait_run_done`
    mais pour les tests qui interrogent directement le JobRunner sans passer
    par l'API REST (le snapshot est un `RunSnapshot` dataclass, pas un dict).

    Retourne True si terminal atteint, False si timeout (le caller decide
    s'il considere ca comme un echec ou un cleanup best-effort).
    """
    deadline = time.monotonic() + _budget(5.0 if timeout_s is None else float(timeout_s))
    while time.monotonic() < deadline:
        snap = runner.get_status(run_id)
        if snap and getattr(snap, "done", False):
            return True
        time.sleep(0.02)
    return False


def wait_runner_status(
    runner: Any,
    run_id: str,
    status: Any,
    timeout_s: float = 5.0,
) -> bool:
    """Poll `runner.get_status(run_id)` jusqu'a `snapshot.status == status`.

    MEGA-HOTFIX bug (5) : factorisation du pattern `_wait_status` utilise dans
    les tests de la state machine job_runner.
    """
    deadline = time.monotonic() + _budget(10.0 if timeout_s is None else float(timeout_s))
    while time.monotonic() < deadline:
        snap = runner.get_status(run_id)
        if snap and snap.status == status:
            return True
        time.sleep(0.02)
    return False


# ---------------------------------------------------------------------------
# Vague M — Sprint 0 (item M-00) : fixture migration DB pre-existante
# ---------------------------------------------------------------------------


def _project_migrations_dir() -> Path:
    """Retourne le dossier `cinesort/infra/db/migrations/` du repo courant.

    Resolu relativement a ce fichier (`tests/_helpers.py`), donc le helper
    n'a pas besoin d'un environnement particulier (CI, dev local, worktree).
    """
    here = Path(__file__).resolve()
    repo_root = here.parents[1]
    return repo_root / "cinesort" / "infra" / "db" / "migrations"


def existing_db_fixture(
    target_schema_version: int,
    *,
    migrations_dir: Path | None = None,
    tmp_path: Path | None = None,
) -> Tuple[Path, sqlite3.Connection]:
    """Cree une SQLite temporaire, applique migrations 001..N <= target_schema_version.

    Memoire `feedback_sqlite_migration_test_existing_db` : toute migration
    SQL doit etre testee sur une DB PRE-EXISTANTE (ancien schema) et pas
    uniquement sur fresh DB. Cette fixture mutualise la creation d'une DB
    "ancienne" arretee a une version donnee, qu'un test peut ensuite faire
    avancer (ex: appliquer la migration N+1 nouvelle pour P-04, P-05, etc.).

    Reutilise par : P-04 (undo extend 005), P-05 (quarantine 030),
    O-06 (timeline 028), R-04 (HDR structured), et tout futur test SQL.

    Implementation : reutilise `cinesort.infra.db.migration_manager.MigrationManager`
    pour la coherence — le helper n'a pas son propre parseur SQL. On copie
    les migrations 001..N dans un dossier temporaire et on laisse le manager
    les appliquer. PRAGMA `user_version` correctement positionne a la fin.

    Args:
        target_schema_version: version maximale appliquee (incluse).
            Si 0 ou negatif, DB vierge (aucune migration).
        migrations_dir: dossier source des migrations (defaut : repo CineSort).
        tmp_path: dossier ou creer le fichier .sqlite. Defaut : tempfile.mkdtemp.

    Returns:
        (db_path, connection) : le caller doit fermer la connexion et nettoyer
        le tempdir (ou laisser le GC le faire).

    Raises:
        FileNotFoundError: si le dossier migrations n'existe pas.
        sqlite3.DatabaseError: si une migration echoue.
    """
    src_migrations = (migrations_dir or _project_migrations_dir()).resolve()
    if not src_migrations.is_dir():
        raise FileNotFoundError(
            f"Migrations dir introuvable: {src_migrations}. Specifier migrations_dir explicitement."
        )

    tmp_root = Path(tmp_path) if tmp_path is not None else Path(tempfile.mkdtemp(prefix="cinesort_existing_db_"))
    tmp_root.mkdir(parents=True, exist_ok=True)

    db_path = tmp_root / "store.sqlite3"

    # Si target <= 0 : DB vierge, on retourne juste une connection vide.
    if target_schema_version <= 0:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA user_version = 0")
        return db_path, conn

    # On copie les migrations <= target_schema_version dans un sous-dossier
    # temporaire, puis on lance MigrationManager dessus. Cette indirection
    # garantit qu'on ne fait jamais avancer la DB au-dela de la version cible
    # (par construction le manager ne voit que les fichiers presents).
    staged = tmp_root / "migrations"
    staged.mkdir(parents=True, exist_ok=True)

    import re as _re

    pattern = _re.compile(r"^(?P<version>\d+)_.*\.sql$")
    copied = 0
    for src in sorted(src_migrations.glob("*.sql")):
        m = pattern.match(src.name)
        if not m:
            continue
        version = int(m.group("version"))
        if version > target_schema_version:
            continue
        dst = staged / src.name
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        copied += 1

    if copied == 0:
        # Aucune migration <= target -> DB vierge avec user_version forcee
        conn = sqlite3.connect(str(db_path))
        conn.execute(f"PRAGMA user_version = {int(target_schema_version)}")
        return db_path, conn

    # Import tardif : evite de payer le cout d'import du backend SQLite
    # complet quand les tests n'utilisent pas cette fixture.
    from cinesort.infra.db.migration_manager import MigrationManager

    manager = MigrationManager(db_path=db_path, migrations_dir=staged)
    final_version = manager.apply()

    if final_version != target_schema_version:
        # Sanity check : si la derniere migration <= target n'est pas
        # exactement target, on log mais on n'echoue pas (cas legitime :
        # target=27 demande la derniere migration appliquee = 27 OK).
        # Echec uniquement si on a depasse, ce qui ne devrait pas arriver
        # grace au filtre ci-dessus.
        if final_version > target_schema_version:
            raise AssertionError(
                f"existing_db_fixture: schema cible {target_schema_version} mais DB est a {final_version} apres apply"
            )

    conn = sqlite3.connect(str(db_path))
    return db_path, conn
