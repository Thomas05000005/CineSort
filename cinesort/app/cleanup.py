from __future__ import annotations

import logging
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Set

from cinesort.app._dir_utils import is_dir_empty, is_reparse_point, stat_is_reparse_point
from cinesort.app.move_journal import atomic_move
from cinesort.domain.core import (
    RESIDUAL_IMAGE_EXTS,
    RESIDUAL_NFO_EXTS,
    RESIDUAL_SUBTITLE_EXTS,
    RESIDUAL_TEXT_EXTS,
    ensure_inside_root,
    windows_safe,
)

_logger = logging.getLogger(__name__)

# Issue #517 : un sidecar credible ne pese pas 500 Mo. Au-dela, un fichier dont
# l'extension est dans une famille residuelle (.txt, .jpg, .nfo...) est presume
# etre autre chose qu'un sidecar — une video renommee, une archive — et le
# dossier devient `ambiguous` : classement par extension SEULE ecarte.
MAX_RESIDUAL_SIDECAR_BYTES = 500 * 1024 * 1024

if TYPE_CHECKING:
    from cinesort.domain.core import ApplyResult, Config


def _collect_root_all_empty_dirs(cfg: "Config") -> List[Path]:
    out: List[Path] = []
    try:
        entries = [p for p in cfg.root.iterdir() if p.is_dir()]
    except OSError:
        return out
    for directory in entries:
        if is_dir_empty(directory):
            out.append(directory)
    return out


def _residual_allowed_exts(cfg: "Config") -> Set[str]:
    allowed: Set[str] = set()
    if cfg.cleanup_residual_include_nfo:
        allowed.update(RESIDUAL_NFO_EXTS)
    if cfg.cleanup_residual_include_images:
        allowed.update(RESIDUAL_IMAGE_EXTS)
    if cfg.cleanup_residual_include_subtitles:
        allowed.update(RESIDUAL_SUBTITLE_EXTS)
    if cfg.cleanup_residual_include_texts:
        allowed.update(RESIDUAL_TEXT_EXTS)
    return allowed


def _residual_cleanup_families(cfg: "Config") -> List[str]:
    families: List[str] = []
    if cfg.cleanup_residual_include_nfo:
        families.append("NFO/XML")
    if cfg.cleanup_residual_include_images:
        families.append("Images")
    if cfg.cleanup_residual_include_subtitles:
        families.append("Sous-titres")
    if cfg.cleanup_residual_include_texts:
        families.append("Textes")
    return families


def _classify_cleanable_residual_dir(cfg: "Config", path: Path) -> str:
    """Classe un dossier candidat (eligible/empty/has_video/ambiguous/symlink/...).

    Renvoie une étiquette utilisée par le preview et le move pour distinguer les dossiers
    sûrs à déplacer (`eligible`/`empty`) des dossiers à protéger (vidéos, symlinks).

    Issue #517 — `path` lui-même est testé AVANT toute énumération : une jonction
    NTFS de premier niveau (`root\\DisqueMutualisé` -> `D:\\...`) passe `is_dir()`
    et `rglob` descend dans sa cible, si bien que le classement se décidait sur des
    fichiers situés HORS de la bibliothèque, puis déplaçait le point de montage
    vers `_Nettoyage`. Sur ce chemin destructif, ne pas traverser est toujours
    plus sûr que traverser.
    """
    if not path.exists() or not path.is_dir():
        return "invalid"
    if is_reparse_point(path):
        return "symlink"
    if is_dir_empty(path):
        return "empty"

    allowed_exts = _residual_allowed_exts(cfg)
    if not allowed_exts:
        return "disabled"

    saw_file = False
    try:
        for item in path.rglob("*"):
            # Issue #567 — UN SEUL `lstat()` par entree. La version precedente en
            # faisait quatre pour un fichier (`is_reparse_point` + `is_dir` +
            # `is_file` + `stat().st_size`), chacun etant un aller-retour reseau
            # sur une bibliotheque SMB/NAS. Les quatre questions se repondent sur
            # le meme `stat_result`, sans changer un seul verdict :
            #   - le point d'analyse est ecarte EN PREMIER, donc au-dela de ce
            #     test `lstat()` et `stat()` decrivent la meme entree (type,
            #     taille) — d'ou l'equivalence avec `is_dir`/`is_file`/`st_size` ;
            #   - un `lstat()` qui echoue rendait deja `is_reparse_point` True,
            #     donc "symlink" reste la reponse au sens restrictif.
            try:
                st = item.lstat()
            except (OSError, ValueError):
                return "symlink"
            if stat_is_reparse_point(st):
                return "symlink"
            if stat.S_ISDIR(st.st_mode):
                continue
            if not stat.S_ISREG(st.st_mode):
                return "ambiguous"
            saw_file = True
            ext = item.suffix.lower()
            # `{".iso"}` n'alloue rien : l'operande droite d'un `in` litteral est
            # compilee en `frozenset` CONSTANT (verifie : `co_consts` contient
            # `frozenset({'.iso'})` et le bytecode ne contient aucun `BUILD_SET`).
            # La hisser au niveau module ne gagnerait donc rien.
            if ext in cfg.video_exts or ext in {".iso"}:
                return "has_video"
            if st.st_size > MAX_RESIDUAL_SIDECAR_BYTES:
                return "ambiguous"
            if ext not in allowed_exts:
                return "ambiguous"
    except OSError:
        return "ambiguous"
    return "eligible" if saw_file else "no_files"


def _is_cleanable_residual_dir(cfg: "Config", path: Path) -> bool:
    return _classify_cleanable_residual_dir(cfg, path) == "eligible"


def _collect_root_all_dirs(cfg: "Config") -> List[Path]:
    out: List[Path] = []
    try:
        entries = [p for p in cfg.root.iterdir() if p.is_dir()]
    except OSError:
        return out
    for directory in entries:
        out.append(directory)
    return out


def _residual_cleanup_skip_names(cfg: "Config", bucket_root: Path) -> Set[str]:
    skip_names = {
        bucket_root.name.lower(),
        "_review",
        cfg.collection_root_name.lower(),
        cfg.empty_folders_folder_name.lower(),
    }
    if cfg.collection_root_name.lower() != "collection":
        skip_names.add("collection")
    return skip_names


def _residual_cleanup_candidates(
    cfg: "Config",
    touched_top_level_dirs: Set[Path],
    *,
    bucket_root: Path,
) -> List[Path]:
    """Liste les dossiers de premier niveau candidats au nettoyage résiduel.

    Filtre selon le scope (touched_only vs all), exclut les dossiers système
    (collection, bucket cible, dossiers en `_*`) et garde l'ordre alphabétique.
    """
    if cfg.cleanup_residual_folders_scope == "touched_only":
        raw_candidates = sorted(
            {p for p in touched_top_level_dirs if p.parent == cfg.root}, key=lambda p: p.name.lower()
        )
    else:
        raw_candidates = sorted(_collect_root_all_dirs(cfg), key=lambda p: p.name.lower())

    skip_names = _residual_cleanup_skip_names(cfg, bucket_root)
    out: List[Path] = []
    for src in raw_candidates:
        if not src.exists() or not src.is_dir():
            continue
        if src.parent != cfg.root:
            continue
        if src.name.lower() in skip_names:
            continue
        if src.name.startswith("_"):
            continue
        out.append(src)
    return out


def preview_cleanup_residual_folders(cfg: "Config", touched_top_level_dirs: Set[Path]) -> Dict[str, Any]:
    """Construit le rapport de prévisualisation du nettoyage des dossiers résiduels.

    Inventorie les dossiers candidats sans rien déplacer puis renvoie compteurs
    (eligibles, vidéos bloquées, ambigus, vides, symlinks) + échantillons + statut
    affichables tels quels par l'UI.
    """
    cfg = cfg.normalized()
    bucket_root = cfg.root / cfg.cleanup_residual_folders_folder_name
    families = _residual_cleanup_families(cfg)

    preview: Dict[str, Any] = {
        "enabled": bool(cfg.cleanup_residual_folders_enabled),
        "target_folder_name": str(cfg.cleanup_residual_folders_folder_name),
        "target_folder_path": str(bucket_root),
        "scope": str(cfg.cleanup_residual_folders_scope),
        "families": families,
        "candidates_considered": 0,
        "probable_eligible_count": 0,
        "empty_dir_count": 0,
        "has_video_count": 0,
        "ambiguous_count": 0,
        "symlink_count": 0,
        "no_files_count": 0,
        "sample_eligible_dirs": [],
        "sample_video_blocked_dirs": [],
        "sample_ambiguous_dirs": [],
        "sample_empty_dirs": [],
        "sample_symlink_dirs": [],
        "status": "disabled",
        "reason_code": "disabled",
        "message": "Nettoyage résiduel désactivé.",
    }

    if not cfg.cleanup_residual_folders_enabled:
        return preview

    candidates = _residual_cleanup_candidates(cfg, touched_top_level_dirs, bucket_root=bucket_root)
    preview["candidates_considered"] = int(len(candidates))

    if not families:
        preview["status"] = "no_action_likely"
        preview["reason_code"] = "no_families_enabled"
        preview["message"] = "Nettoyage activé mais aucune famille résiduelle n'est activée."
        return preview

    for src in candidates:
        reason = _classify_cleanable_residual_dir(cfg, src)
        if reason == "eligible":
            preview["probable_eligible_count"] = int(preview["probable_eligible_count"]) + 1
            if len(preview["sample_eligible_dirs"]) < 5:
                preview["sample_eligible_dirs"].append(str(src))
        elif reason == "empty":
            preview["empty_dir_count"] = int(preview["empty_dir_count"]) + 1
            if len(preview["sample_empty_dirs"]) < 5:
                preview["sample_empty_dirs"].append(str(src))
        elif reason == "has_video":
            preview["has_video_count"] = int(preview["has_video_count"]) + 1
            if len(preview["sample_video_blocked_dirs"]) < 5:
                preview["sample_video_blocked_dirs"].append(str(src))
        elif reason == "symlink":
            preview["symlink_count"] = int(preview["symlink_count"]) + 1
            if len(preview["sample_symlink_dirs"]) < 5:
                preview["sample_symlink_dirs"].append(str(src))
        elif reason == "no_files":
            preview["no_files_count"] = int(preview["no_files_count"]) + 1
        else:
            preview["ambiguous_count"] = int(preview["ambiguous_count"]) + 1
            if len(preview["sample_ambiguous_dirs"]) < 5:
                preview["sample_ambiguous_dirs"].append(str(src))

    probable = int(preview["probable_eligible_count"] or 0)
    if probable > 0:
        preview["status"] = "ready"
        preview["reason_code"] = "eligible"
        preview["message"] = (
            f"Nettoyage résiduel : {probable} dossier(s) probablement éligible(s) "
            f"vers {cfg.cleanup_residual_folders_folder_name}."
        )
        return preview

    preview["status"] = "no_action_likely"
    if int(preview["candidates_considered"] or 0) == 0 and cfg.cleanup_residual_folders_scope == "touched_only":
        preview["reason_code"] = "scope_touched_only_none"
        preview["message"] = (
            "Nettoyage activé mais le scope touched_only n'a trouvé aucun dossier top-level touché à inspecter."
        )
    elif int(preview["has_video_count"] or 0) > 0 and int(preview["ambiguous_count"] or 0) == 0:
        preview["reason_code"] = "videos_present"
        preview["message"] = "Aucun dossier sidecar-only éligible : des vidéos sont encore présentes."
    elif int(preview["ambiguous_count"] or 0) > 0:
        preview["reason_code"] = "ambiguous_extensions"
        preview["message"] = "Aucun dossier éligible : extensions ambiguës ou prudence moteur."
    elif int(preview["empty_dir_count"] or 0) > 0 and int(preview["candidates_considered"] or 0) == int(
        preview["empty_dir_count"] or 0
    ):
        preview["reason_code"] = "empty_only"
        preview["message"] = "Aucun dossier résiduel non vide éligible : seuls des dossiers vides relèvent de _Vide."
    else:
        preview["reason_code"] = "none_eligible"
        preview["message"] = "Aucun dossier sidecar-only éligible trouvé pour ce run."
    return preview


def _move_dir_without_destructive_fallback(
    record_op: Callable[[Dict[str, Any]], None] | None,
    *,
    src: Path,
    dst: Path,
) -> None:
    """Déplace un DOSSIER entier sans jamais dégrader en copie destructive.

    `shutil.move` retombe sur copytree + rmtree dès que `os.rename` échoue — y
    compris pour un banal verrou Windows sur UN fichier interne (indexeur,
    antivirus, aperçu Explorateur, éditeur de .nfo). Mesuré sur Windows 11 avec
    un simple `open()` sur `BBB/film.srt` :

    - `Path.rename` -> PermissionError WinError 5, source INTACTE (3 fichiers),
      destination ABSENTE ; rien n'a bougé.
    - `shutil.move`  -> PermissionError WinError 32, destination contenant les
      3 fichiers ET source amputée de `film.nfo` : contenu dédoublé, source
      éventrée, et comme `record_apply_op` n'est appelé qu'APRÈS le move, cette
      copie n'est journalisée nulle part — donc invisible de l'undo.

    Ici `bucket_root` est sous `cfg.root` et `src` est un enfant direct de
    `cfg.root` : le même volume est garanti en pratique, `os.rename` est
    atomique et « tout ou rien ». D'où `allow_copy_fallback=False`, qui ne
    dégrade en copie que sur un vrai EXDEV.

    On reste DANS `atomic_move` (issue #670) : son journal write-ahead ne sert
    pas qu'à rattraper la non-atomicité de la copie, il est aussi la seule trace
    du déplacement si l'app meurt entre le `rename` et le `record_apply_op` qui
    suit chez l'appelant. Sortir ce site du journal rendrait un tel déplacement
    invisible de l'undo ET de la réconciliation au boot.
    """
    atomic_move(record_op, src=src, dst=dst, op_type="MOVE_DIR", allow_copy_fallback=False)


def _move_dirs_to_bucket(
    candidates: List[Path],
    *,
    is_eligible: Callable[[Path], bool],
    bucket_root: Path,
    dry_run: bool,
    log: Callable[[str, str], None],
    log_prefix: str,
    res: "ApplyResult",
    counter_attr: str,
    record_op: Callable[[Dict[str, Any]], None] | None = None,
) -> int:
    """Déplace chaque dossier éligible vers `bucket_root` et journalise l'opération.

    Isolation PAR DOSSIER (le résultat n'était pas isolé auparavant) : un verrou
    sur un seul dossier faisait remonter l'exception jusqu'au garde F10 de
    `apply_core`, qui n'est posé qu'autour de la fonction ENTIÈRE. Conséquences
    mesurées : les dossiers suivants n'étaient jamais traités, et le `+=` du
    compteur étant sauté en bloc, le résumé affichait « aucun déplacement »
    alors que des dossiers avaient bel et bien quitté la bibliothèque.

    `res.<counter_attr>` est donc incrémenté à CHAQUE succès, et chaque échec
    est compté dans `res.errors` puis décrit dans `res.error_messages`.

    Ces deux compteurs restent sous `if not dry_run` (#561) : en prévisualisation
    aucun dossier ne bouge, et `res.<counter_attr>` est remonté tel quel à l'UI
    (`apply_core` -> rapport d'apply). Un incrément en dry-run annoncerait à
    l'utilisateur des dossiers partis vers `_Vide` / `_Nettoyage` qui sont
    toujours en place.

    Renvoie le nombre de dossiers réellement déplacés (0 si dry_run ou aucun
    éligible).
    """
    # Cycle app.cleanup <-> app.apply_core : apply_core importe cleanup en
    # top-level donc on garde apply_core en import tardif ici.
    from cinesort.app.apply_core import _append_error_message
    from cinesort.app.apply_core import record_apply_op as _record_apply_op
    from cinesort.app.apply_core import unique_path as _unique_path

    moved = 0
    for src in candidates:
        dst: Path | None = None
        try:
            if not is_eligible(src):
                continue
            dst = _unique_path(bucket_root / windows_safe(src.name))
            log("INFO", f"{log_prefix}: {src} -> {dst}")
            _logger.info("cleanup: %s -> %s (dry_run=%s)", src.name, dst, dry_run)
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                _move_dir_without_destructive_fallback(record_op, src=src, dst=dst)
                # Comptage ICI, juste apres le rename abouti : le compteur suit
                # la realite disque dossier par dossier (un echec sur le suivant
                # ne doit plus faire perdre ce qui a deja bouge).
                # ...et SOUS `if not dry_run` (#561) : en dry-run rien ne bouge,
                # annoncer des dossiers deplaces dans la preview serait un
                # mensonge expose tel quel a l'UI.
                moved += 1
                setattr(res, counter_attr, int(getattr(res, counter_attr, 0) or 0) + 1)
                _record_apply_op(
                    record_op,
                    op_type="MOVE_DIR",
                    src_path=src,
                    dst_path=dst,
                    reversible=True,
                )
        except OSError as exc:
            res.errors += 1
            _append_error_message(res, f"{log_prefix} {src.name} : {exc}")
            log("ERROR", f"{log_prefix} echoue sur {src} (les autres dossiers continuent) : {exc}")
            _logger.warning("cleanup: %s echoue sur %s: %s", log_prefix, src, exc)
            if dst is not None and dst.exists():
                # Reste possible uniquement sur le chemin EXDEV (copie). On NE
                # SUPPRIME PAS `dst` : la copie est un sur-ensemble de ce qui
                # reste dans `src`, l'effacer detruirait definitivement les
                # fichiers deja retires de la source. On le signale, c'est tout.
                partial = (
                    f"{log_prefix} {src.name} : copie partielle laissee dans {dst} — la source est "
                    "incomplete, comparez les deux dossiers AVANT toute suppression."
                )
                _append_error_message(res, partial)
                log("ERROR", partial)
            continue
    return moved


def _move_residual_top_level_dirs(
    cfg: "Config",
    *,
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    touched_top_level_dirs: Set[Path],
    record_op: Callable[[Dict[str, Any]], None] | None = None,
) -> None:
    """Déplace les dossiers résiduels de premier niveau vers le bucket de nettoyage.

    No-op si le nettoyage résiduel est désactivé. Met à jour `res.cleanup_residual_folders_moved_count`.
    """
    if not cfg.cleanup_residual_folders_enabled:
        return

    bucket_root = cfg.root / cfg.cleanup_residual_folders_folder_name
    ensure_inside_root(cfg, bucket_root)
    candidates = _residual_cleanup_candidates(cfg, touched_top_level_dirs, bucket_root=bucket_root)

    # `res` est incremente dossier par dossier DANS `_move_dirs_to_bucket` (et
    # non par un `+=` final) : un echec sur un dossier ne doit plus faire perdre
    # le compte des dossiers deja deplaces.
    _move_dirs_to_bucket(
        candidates,
        is_eligible=lambda src: _classify_cleanable_residual_dir(cfg, src) == "eligible",
        bucket_root=bucket_root,
        dry_run=dry_run,
        log=log,
        log_prefix="DOSSIER NETTOYAGE",
        res=res,
        counter_attr="cleanup_residual_folders_moved_count",
        record_op=record_op,
    )


def _move_empty_top_level_dirs(
    cfg: "Config",
    *,
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    touched_top_level_dirs: Set[Path],
    record_op: Callable[[Dict[str, Any]], None] | None = None,
) -> None:
    """Déplace les dossiers vides de premier niveau vers le bucket dédié.

    No-op si l'option `move_empty_folders_enabled` est désactivée. Met à jour
    `res.empty_folders_moved_count`.

    Issue #517 — même angle mort que le nettoyage résiduel : une jonction NTFS
    dont la cible est vide (volume démonté, disque mutualisé vidé) est vue
    `is_dir_empty() == True` et le point de montage partirait vers `_Vide`.
    """
    if not cfg.move_empty_folders_enabled:
        return

    bucket_root = cfg.root / cfg.empty_folders_folder_name
    ensure_inside_root(cfg, bucket_root)

    if cfg.empty_folders_scope == "touched_only":
        raw_candidates = sorted(
            {p for p in touched_top_level_dirs if p.parent == cfg.root}, key=lambda p: p.name.lower()
        )
    else:
        raw_candidates = sorted(_collect_root_all_empty_dirs(cfg), key=lambda p: p.name.lower())

    skip_names = {
        bucket_root.name.lower(),
        "_review",
        cfg.collection_root_name.lower(),
    }
    if cfg.collection_root_name.lower() != "collection":
        skip_names.add("collection")

    candidates = [
        src
        for src in raw_candidates
        if src.exists()
        and src.is_dir()
        and src.parent == cfg.root
        and src.name.lower() not in skip_names
        and not src.name.startswith("_")
    ]

    _move_dirs_to_bucket(
        candidates,
        is_eligible=lambda src: is_dir_empty(src) and not is_reparse_point(src),
        bucket_root=bucket_root,
        dry_run=dry_run,
        log=log,
        log_prefix="DOSSIER VIDE",
        res=res,
        counter_attr="empty_folders_moved_count",
        record_op=record_op,
    )
