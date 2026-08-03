"""CR-2 audit QA 20260429 — backup automatique de la base SQLite.

Probleme : aucun backup automatique. Une corruption disque (kill pendant
WAL checkpoint, secteur defectueux, AV qui truncate le fichier) detruit
toute la bibliotheque (films matches, decisions, scores, historique).

Solution :
- `backup_db(src, dst)` utilise `sqlite3.Connection.backup()` natif
  (snapshot online sur online connection, fonctionne meme en WAL avec
  des connexions actives).
- `rotate_backups(dir, max_count)` garde les N plus recents, supprime
  le reste.
- Hook AVANT chaque migration au boot (cf SQLiteStore.initialize).
- Hook APRES chaque apply reel (cf apply_support.apply_changes).
- Helper `restore_backup(backup, target)` pour restauration manuelle
  via UI (UI ulterieure).

Ecriture ATOMIQUE (#669, #468) : `backup_db` comme `restore_backup` copient
d'abord vers un fichier de travail voisin, puis le publient par `os.replace`.
Une destination n'existe donc jamais dans un etat partiel, et la base
principale n'est remplacee qu'a partir d'une image complete ET validee, apres
purge des sidecars `-wal`/`-shm`/`-journal` de la generation precedente.

Naming convention des backups :
    cinesort.{timestamp}.{trigger}.bak
ou trigger ∈ {pre_migration, post_apply, manual}.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import List, Optional, Tuple

_logger = logging.getLogger(__name__)

DEFAULT_MAX_BACKUPS = 5
BACKUP_SUFFIX = ".bak"
MAX_BACKUP_ATTEMPTS = 10000

# Sidecars qu'une base SQLite peut laisser a cote de son fichier principal.
# `-wal`/`-shm` : mode WAL. `-journal` : mode rollback (journal "chaud").
# Tous les trois sont REJOUES a l'ouverture suivante et appartiennent a la
# GENERATION du fichier principal : en survivre a un remplacement du `.sqlite`
# revient a rejouer les pages d'une autre base par-dessus celle qu'on vient de
# restaurer (cf #468).
SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")

# Nombre de tentatives de `os.replace` avant abandon. Sur Windows, un antivirus
# ou Volume Shadow Copy tient un handle transitoire sur la destination et fait
# lever PermissionError (WinError 5/32) ; meme borne que
# `cinesort.infra.state.atomic_write_json` (R8-026).
_REPLACE_ATTEMPTS = 5


def _unique_tmp_path(final_path: Path) -> Path:
    """Chemin temporaire VOISIN de `final_path` (donc meme systeme de fichiers,
    condition necessaire pour que `os.replace` soit atomique).

    Le nom est unique (pid + uuid) pour qu'un second ecrivain ne recycle jamais
    le `.tmp` d'un premier, et il ne se termine PAS par `.bak` : `list_backups`
    (glob `*.bak`) ne peut donc jamais proposer un fichier de travail comme
    source de restauration.
    """
    return final_path.with_name(f"{final_path.name}.{os.getpid()}.{uuid.uuid4().hex[:12]}.tmp")


def _purge_sidecars(db_path: Path) -> None:
    """Supprime les sidecars `-wal`/`-shm`/`-journal` de `db_path` (best-effort).

    Un echec d'unlink est logge sans lever : il sera de toute facon revele par
    l'ouverture suivante, et faire echouer une restauration deja preparee
    laisserait l'utilisateur sans base du tout.
    """
    for suffix in SQLITE_SIDECAR_SUFFIXES:
        sidecar = db_path.with_name(db_path.name + suffix)
        try:
            sidecar.unlink(missing_ok=True)
        except OSError as exc:
            _logger.warning("purge sidecar %s impossible: %s", sidecar.name, exc)


def _discard_tmp(tmp_path: Path) -> None:
    """Efface un fichier de travail et ses eventuels sidecars (best-effort)."""
    try:
        tmp_path.unlink(missing_ok=True)
    except OSError as exc:
        _logger.warning("nettoyage du fichier de travail %s impossible: %s", tmp_path.name, exc)
    _purge_sidecars(tmp_path)


def _fsync_file(path: Path) -> None:
    """Force l'ecriture des pages sur le disque avant publication.

    Best-effort assume : `os.replace` reste atomique meme si le fsync echoue
    (seule la durabilite en cas de coupure secteur est concernee). Refuser une
    RESTAURATION pour un fsync capricieux (partage SMB, disque amovible)
    laisserait l'utilisateur sans base alors que la copie est correcte.
    """
    try:
        with open(path, "r+b") as handle:  # r+b : fsync exige un handle en ecriture sous Windows
            os.fsync(handle.fileno())
    except OSError as exc:
        _logger.warning("fsync de %s impossible (durabilite non garantie): %s", path.name, exc)


def _replace_with_retry(tmp_path: Path, final_path: Path) -> None:
    """`os.replace` avec retry borne sur PermissionError (verrou AV Windows).

    L'atomicite n'est pas affectee : `os.replace` publie tout ou rien. Apres
    epuisement des tentatives on RE-LEVE — la destination est alors restee
    intacte, ce qui est le sens restrictif voulu sur un chemin destructif.
    """
    last_exc: Optional[PermissionError] = None
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(tmp_path, final_path)
            return
        except PermissionError as exc:
            last_exc = exc
            if attempt < _REPLACE_ATTEMPTS - 1:
                time.sleep(0.05 * (attempt + 1))
    if last_exc is not None:
        raise last_exc


def _quick_check_status(path: Path) -> str:
    """`PRAGMA quick_check` sur un fichier SQLite, sans jamais lever.

    Retourne "ok", le message brut de SQLite, ou "error: <exc>".
    `quick_check` (et non `integrity_check`) : il verifie la structure des
    btrees — ce qui detecte une image tronquee ou des pages perdues — sans
    payer le recoupement table/index, hors de propos pour valider une COPIE.
    NB : sqlite3.Error n'herite PAS de OSError, les deux sont obligatoires.
    """
    try:
        with closing(sqlite3.connect(str(path))) as conn:
            row = conn.execute("PRAGMA quick_check").fetchone()
            status = str(row[0]) if row else "unknown"
            if status == "ok":
                page_row = conn.execute("PRAGMA page_count").fetchone()
                if not page_row or int(page_row[0]) <= 0:
                    return "page_count=0 (base vide)"
            return status
    except (sqlite3.Error, OSError, TypeError, ValueError) as exc:
        return f"error: {exc}"


def _format_backup_name(stem: str, trigger: str, ts: Optional[float] = None) -> str:
    """Construit le nom du backup : {stem}.{YYYYMMDD-HHMMSS-NNNNNN}Z.{trigger}.bak

    Cf issue #81 (audit-2026-05-12:b1c3) :
    - `gmtime` (UTC) plutot que `localtime` evite les collisions de noms a
      chaque changement DST (le 31 octobre 2h heure d'ete = 1h heure d'hiver,
      memes timestamps formattes deux fois).
    - Suffixe `Z` marque explicitement le fuseau UTC dans le nom.
    - Microsecondes (`NNNNNN`, 6 chiffres) garantissent l'unicite meme
      lorsque deux backups sont declenches dans la meme seconde (cas typique :
      backup pre-migration + post-apply en moins d'une seconde au boot).
    """
    t = float(ts if ts is not None else time.time())
    timestr = time.strftime("%Y%m%d-%H%M%S", time.gmtime(t))
    micros = int(round((t - int(t)) * 1_000_000)) % 1_000_000
    return f"{stem}.{timestr}-{micros:06d}Z.{trigger}{BACKUP_SUFFIX}"


def backup_db(src_path: Path, dst_path: Path) -> Path:
    """Copie atomique de src_path vers dst_path via sqlite3.Connection.backup().

    L'API natif sqlite3 backup() est plus robuste que shutil.copy car :
    - Acquiert un lock partage approprie.
    - Fonctionne meme en WAL avec ecritures concurrentes.
    - Garantit la coherence de la copie (pas de partial write).

    Cree le dossier parent si besoin. Retourne le chemin du backup cree.
    Leve sqlite3.Error en cas d'echec (caller decide quoi faire).
    """
    src = Path(src_path)
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.is_file():
        raise FileNotFoundError(f"Source DB introuvable pour backup: {src}")

    # #669 — ECRITURE ATOMIQUE. `sqlite3.connect(dst)` CREE le fichier
    # destination AVANT meme que `src_conn.backup()` ne commence a copier : toute
    # interruption (source corrompue, disque plein, kill) laissait donc un `.bak`
    # PARTIEL dans backups/. Le nettoyage AUDIT F29 ne couvrait que le cas
    # `st_size == 0` ; un `.bak` partiel NON VIDE restait liste par
    # `list_backups` et pouvait etre elu source d'une restauration.
    # On ecrit desormais dans un fichier de travail voisin, puis on le PUBLIE
    # par `os.replace` : la destination n'existe qu'apres une copie complete, et
    # un `.bak` deja present n'est jamais entame par un backup qui echoue.
    tmp = _unique_tmp_path(dst)
    try:
        # On ouvre une connexion sur la source ET sur le fichier de travail, puis
        # on demande au moteur SQLite de faire le backup (snapshot online).
        with closing(sqlite3.connect(str(src))) as src_conn, closing(sqlite3.connect(str(tmp))) as dst_conn:
            src_conn.backup(dst_conn)
        _purge_sidecars(tmp)
        _fsync_file(tmp)
        _replace_with_retry(tmp, dst)
    finally:
        # No-op apres une publication reussie (le `.tmp` n'existe plus).
        _discard_tmp(tmp)
    _logger.info("backup_db: %s -> %s (%.1f KB)", src.name, dst, dst.stat().st_size / 1024)
    return dst


def list_backups(backup_dir: Path, *, stem_filter: Optional[str] = None) -> List[Path]:
    """Liste les backups d'un dossier, tries du plus recent au plus ancien.

    Si stem_filter fourni, ne retourne que les backups dont le nom commence
    par ce stem (ex: "cinesort").
    """
    backup_dir = Path(backup_dir)
    if not backup_dir.is_dir():
        return []
    candidates = list(backup_dir.glob(f"*{BACKUP_SUFFIX}"))
    if stem_filter:
        prefix = f"{stem_filter}."
        candidates = [p for p in candidates if p.name.startswith(prefix)]
    # Tri par mtime decroissant (plus recent d'abord), avec le nom de fichier
    # en cle secondaire (decroissante elle aussi : le nom contient le timestamp
    # formate donc l'ordre alphabetique des noms correspond a l'ordre temporel).
    # Pourquoi la cle secondaire : sur Windows, st_mtime peut etre identique
    # entre plusieurs backups crees a < 15 ms d'intervalle (granularite du
    # timer systeme), ce qui rendait l'ordre non-deterministe et faisait
    # supprimer/retourner le mauvais fichier en rotation.
    candidates.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    return candidates


def rotate_backups(
    backup_dir: Path,
    *,
    max_count: int = DEFAULT_MAX_BACKUPS,
    stem_filter: Optional[str] = None,
) -> Tuple[int, List[Path]]:
    """Supprime les backups au-dela de max_count, retourne (n_kept, deleted_list).

    Tolerant : si un unlink echoue, on log et on continue.
    """
    if max_count < 1:
        max_count = 1
    backups = list_backups(backup_dir, stem_filter=stem_filter)
    if len(backups) <= max_count:
        return len(backups), []
    to_delete = backups[max_count:]
    deleted: List[Path] = []
    for path in to_delete:
        # Issue #382 : sur Windows, AV (Defender, Avast) ou Volume Shadow Copy
        # peuvent tenir un handle transitoire sur le .bak. Retry court (3
        # tentatives, 50/150/300 ms) couvre les fenetres typiques AV sans
        # bloquer le scan. Au-dela, on log warning et on accepte que la
        # rotation soit incomplete ce cycle (sera rejouee au prochain).
        last_exc: Optional[BaseException] = None
        for attempt, delay_s in enumerate((0.0, 0.05, 0.15, 0.3)):
            if delay_s:
                time.sleep(delay_s)
            try:
                path.unlink()
                deleted.append(path)
                _logger.info("rotate_backups: supprime %s", path.name)
                last_exc = None
                break
            except PermissionError as exc:
                last_exc = exc
                continue
            except OSError as exc:
                last_exc = exc
                break
        if last_exc is not None:
            _logger.warning("rotate_backups: unlink %s echoue apres %d tentatives: %s", path, attempt + 1, last_exc)
    return len(backups) - len(deleted), deleted


def _resolve_unique_backup_path(backup_dir: Path, base_name: str) -> Path:
    """Retourne un chemin unique dans `backup_dir` derive de `base_name`.

    Si `base_name` n'existe pas, retourne `backup_dir/base_name`. Sinon insere
    un suffixe `-N` (1, 2, ...) avant le `.bak` final jusqu'a trouver un nom
    libre.

    Pourquoi : sur Windows, `time.time()` a une granularite du timer systeme
    d'environ 15 ms (et `time.time_ns()` aussi). Plusieurs backups declenches
    dans la meme tranche de 15 ms partagent les memes microsecondes formatees
    et donc le meme nom — la seconde ecriture ecrase silencieusement la
    premiere, ce qui fait perdre un backup. Ce helper garantit qu'aucun
    backup precedent ne sera ecrase, meme en rafale.
    """
    candidate = Path(backup_dir) / base_name
    if not candidate.exists():
        return candidate
    # Insere `-N` avant le suffixe .bak (preserve l'extension et le tri par nom)
    if base_name.endswith(BACKUP_SUFFIX):
        stem_part = base_name[: -len(BACKUP_SUFFIX)]
    else:
        stem_part = base_name
    counter = 1
    while counter <= MAX_BACKUP_ATTEMPTS:
        alt_name = f"{stem_part}-{counter}{BACKUP_SUFFIX}"
        alt = Path(backup_dir) / alt_name
        if not alt.exists():
            return alt
        counter += 1
    raise RuntimeError(f"Aucun nom de backup libre apres {MAX_BACKUP_ATTEMPTS} essais dans {backup_dir}")


def backup_db_with_rotation(
    src_path: Path,
    backup_dir: Path,
    *,
    trigger: str,
    max_count: int = DEFAULT_MAX_BACKUPS,
) -> Optional[Path]:
    """Combine backup + rotation : cree un backup nomme automatiquement
    et nettoie les anciens.

    `trigger` : etiquette ("pre_migration" | "post_apply" | "manual" | ...).

    Retourne le chemin du backup cree, ou None si la source n'existe pas
    (cas fresh install — pas de backup utile).
    Tolere les erreurs sqlite3.Error : log + retourne None plutot que
    bloquer un boot ou un apply.
    """
    src = Path(src_path)
    if not src.is_file():
        _logger.debug("backup_db_with_rotation: source absente, skip (fresh install): %s", src)
        return None

    stem = src.stem  # ex: "cinesort" pour cinesort.sqlite
    backup_name = _format_backup_name(stem, trigger)
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = _resolve_unique_backup_path(backup_dir, backup_name)

    try:
        backup_db(src, backup_path)
    except (sqlite3.Error, OSError, PermissionError) as exc:
        _logger.warning("backup_db_with_rotation: backup echoue (%s): %s", trigger, exc)
        return None

    rotate_backups(backup_dir, max_count=max_count, stem_filter=stem)
    return backup_path


def _create_restore_guard(target: Path) -> None:
    """Sauvegarde la cible AVANT de l'ecraser, et decide si le restore peut
    continuer quand cette sauvegarde echoue (#669).

    L'ancien code se contentait d'un `warning` puis poursuivait le restore
    destructif : un disque plein pendant le garde-fou faisait donc perdre la
    base principale SANS filet. Refuser systematiquement serait pire — le
    garde-fou echoue precisement quand la cible est ILLISIBLE, c'est-a-dire
    dans le cas ou l'auto-restore au boot est le plus utile.

    Regle retenue, verifiee positivement plutot que devinee depuis le type
    d'exception (un disque plein remonte en `sqlite3.OperationalError`, pas en
    `OSError`) :
      - cible encore exploitable (`quick_check` == ok) et non sauvegardable
        -> on REFUSE le restore (re-leve). Sens restrictif : mieux vaut ne pas
        restaurer que detruire sans filet une base recuperable.
      - cible deja inexploitable -> il n'y a rien a proteger, on poursuit.
    """
    if not target.is_file():
        return
    # `_resolve_unique_backup_path` : deux restores dans la meme tranche de
    # ~15 ms (granularite du timer Windows) produisent le meme nom formate ; le
    # chemin brut faisait ecraser le garde-fou du premier par celui du second.
    guard_name = _format_backup_name(target.stem, "before_restore")
    guard_path = _resolve_unique_backup_path(target.parent, guard_name)
    try:
        backup_db(target, guard_path)
    except (sqlite3.Error, OSError) as exc:
        target_status = _quick_check_status(target)
        if target_status == "ok":
            _logger.error(
                "restore_backup: garde-fou impossible (%s) alors que la cible est SAINE — restore refuse",
                exc,
            )
            raise
        _logger.warning(
            "restore_backup: garde-fou impossible (%s) mais la cible est deja inexploitable (%s) — on poursuit",
            exc,
            target_status,
        )
        return
    _logger.info("restore_backup: garde-fou cree %s", guard_path.name)


def restore_backup(backup_path: Path, target_path: Path) -> Path:
    """Restaure un backup vers une cible, de facon ATOMIQUE.

    Si la cible existe, elle est d'abord sauvegardee en
    {target}.before_restore.{ts}.bak (defense en profondeur) ; l'echec de cette
    sauvegarde ANNULE le restore tant que la cible est encore exploitable
    (cf `_create_restore_guard`).

    La restauration elle-meme ecrit dans un fichier de travail voisin puis le
    publie par `os.replace` : la cible passe d'une image complete a l'autre,
    jamais par un etat intermediaire (#669). L'image restauree est validee
    (`quick_check`) AVANT publication, et les sidecars `-wal`/`-shm`/`-journal`
    de la cible sont purges pour ne pas rejouer une autre generation par-dessus
    (#468).

    Retourne le chemin de la cible apres restore.
    Leve `FileNotFoundError` si backup_path n'existe pas, `sqlite3.DatabaseError`
    si l'image restauree n'est pas exploitable, et re-leve toute erreur de copie
    ou de publication — dans TOUS ces cas la cible est laissee INTACTE.
    """
    backup = Path(backup_path)
    target = Path(target_path)
    if not backup.is_file():
        raise FileNotFoundError(f"Backup introuvable: {backup}")

    _create_restore_guard(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = _unique_tmp_path(target)
    try:
        # Copie complete du backup dans le fichier de travail. La cible n'est
        # PAS ouverte : une erreur ici (source tronquee, disque plein, kill) ne
        # peut donc plus laisser la base principale a moitie ecrasee.
        with closing(sqlite3.connect(str(backup))) as src_conn, closing(sqlite3.connect(str(tmp))) as dst_conn:
            src_conn.backup(dst_conn)

        # Une copie qui ne leve pas n'est pas une copie exploitable : un `.bak`
        # partiel dont l'en-tete a survecu se copie sans erreur et produit une
        # image malformee. On la valide AVANT de la publier (#669).
        status = _quick_check_status(tmp)
        if status != "ok":
            raise sqlite3.DatabaseError(f"Image restauree inexploitable depuis {backup.name}: {status}")
        _purge_sidecars(tmp)
        _fsync_file(tmp)

        # Purge AVANT le `os.replace` : si le processus meurt entre les deux, la
        # cible reste l'ancienne image sans sidecar (etat coherent, et le
        # garde-fou existe). Dans l'ordre inverse, une mort dans la meme fenetre
        # laisserait la NOUVELLE image avec le `-wal` de l'ANCIENNE, rejoue en
        # silence au boot suivant (#468) — corruption indetectable.
        _purge_sidecars(target)
        _replace_with_retry(tmp, target)
    finally:
        # No-op apres une publication reussie (le `.tmp` n'existe plus).
        _discard_tmp(tmp)
    _logger.info("restore_backup: %s -> %s", backup.name, target)
    return target
