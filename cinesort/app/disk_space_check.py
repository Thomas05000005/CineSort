"""H-2 audit QA 20260428 — pre-check espace disque avant apply.

Refuse de demarrer un apply si la destination n'a pas assez d'espace pour
absorber la somme des fichiers a deplacer. Sur Windows, shutil.move est une
copie + delete des qu'on traverse les volumes, donc l'espace disque cible
doit pouvoir contenir l'ensemble en transit.

Strategie : conservatrice (somme totale + 10% de marge). Si meme volume,
l'espace utilise reste constant donc on est sur-protecteur, mais c'est
sans risque. Si volumes differents, on protege contre l'apply qui se
coupe a mi-parcours par disque plein.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

_logger = logging.getLogger(__name__)

# Marge minimale absolue : meme si la somme calculee est petite, on refuse
# si moins de 100 MB libres au total (zone tampon FS, journal SQLite, logs...).
_MIN_FREE_BYTES = 100 * 1024 * 1024  # 100 MB

# Marge proportionnelle au-dessus de la somme estimee.
_SAFETY_MARGIN = 0.10  # 10%

# Kinds dont la row PARTAGE son dossier avec d'autres rows du plan.
# INVARIANT DESTRUCTIF (cf. domain/core.py:401) : SEUL "single" possede un
# dossier dedie. Pour ces kinds-la, `apply_collection_item` / `apply_tv_episode`
# ne deplacent QUE le fichier video (+ ses sidecars) vers un sous-dossier du
# MEME dossier : sommer l'arborescence entiere la compterait autant de fois
# qu'elle contient de films, et ressusciterait le faux "espace insuffisant"
# que le filtre "approuves seulement" (Fix R6-04, apply_support.py) elimine.
_SHARED_FOLDER_KINDS = frozenset({"collection", "tv_episode", "extra"})


def _dir_tree_size(folder: Path) -> int:
    """Somme RECURSIVE de la taille des fichiers sous `folder`.

    Aligne l'estimation sur ce que fait reellement l'apply : `merge_dir_safe`
    (apply_core.py) parcourt `src_dir.rglob("*")`, et un `folder.rename(dst)`
    emporte de toute facon l'arborescence complete. Une somme non recursive
    OMET tout ce qui vit dans un sous-dossier (extras, sous-titres, artwork)
    et sous-estime donc l'espace necessaire — l'erreur permissive qu'on ne
    peut pas se permettre sur un chemin destructif.

    Un fichier illisible est ignore ; un dossier illisible n'annule PAS ce qui
    a deja ete somme (on garde le total partiel, plus conservateur que 0).
    `rglob` ne suit pas les liens symboliques de dossier : pas de boucle.
    """
    total = 0
    try:
        for entry in folder.rglob("*"):
            try:
                if not entry.is_file():
                    continue
                total += int(entry.stat().st_size)
            except (OSError, PermissionError):
                continue
    except (OSError, PermissionError):
        return total
    return total


def _row_estimated_size(row: Any) -> int:
    """Taille estimee des fichiers que ce row va deplacer.

    Deux granularites, calquees sur celle de l'apply (cf. apply_core.py) :

    - kind partage (`collection`, `tv_episode`, `extra`) avec un `video`
      connu : seul ce fichier bouge, et vers un sous-dossier du meme dossier.
      On somme le seul `folder/video`.
    - tout le reste (`single`, ou kind absent/inconnu) : l'apply deplace le
      DOSSIER ENTIER, recursivement. On somme donc tout l'arbre. C'est aussi
      le defaut choisi quand le kind est inconnu, par coherence avec
      `_normalize_plan_kind` (plan_support_core.py) qui retombe sur "single",
      la granularite la plus destructive.

    Le resultat n'est jamais inferieur a la taille du video principal : si
    l'arbre est illisible mais que le video, lui, se stat, on garde ce dernier.
    Si tout echoue : 0 (mieux laisser l'apply tenter que bloquer sur un edge
    case ou l'on ne sait rien).
    """
    folder_str = str(getattr(row, "folder", "") or "")
    video_str = str(getattr(row, "video", "") or "")
    if not folder_str:
        return 0

    folder = Path(folder_str)
    kind = str(getattr(row, "kind", "") or "").strip().lower()

    video_size = 0
    if video_str:
        try:
            video_size = int((folder / video_str).stat().st_size)
        except (OSError, PermissionError):
            video_size = 0

    if video_str and kind in _SHARED_FOLDER_KINDS:
        return video_size

    return max(_dir_tree_size(folder), video_size)


def estimate_apply_size(rows: List[Any], approved_keys: set) -> int:
    """Somme estimee des octets a deplacer par les rows approuves.

    `approved_keys` : ensemble des row_id qui seront effectivement appliques.

    Les rows NON approuvees sont volontairement exclues (Fix R6-04, cf.
    apply_support.py) : sans ce filtre, un run a 990 refusees et 10 approuvees
    declenchait un faux "espace disque insuffisant". Elles ne consomment rien
    non plus quand `quarantine_unapproved` est actif : la quarantaine les
    deplace sous `<root>/_review/`, donc sur le volume que l'on mesure — les
    compter reviendrait a facturer deux fois le meme volume.

    On ne somme donc QUE les rows explicitement approuvees. Une row au `row_id`
    vide ne peut par construction jamais figurer dans `approved_keys` (les
    cles viennent des decisions), donc elle est exclue — l'ancien garde
    `if rid and rid not in approved_keys` la laissait passer et gonflait
    l'estimation, jusqu'a un faux "espace disque insuffisant" qui BLOQUE
    l'apply (#698). Cf la regle de revue "sentinelle falsy" dans
    cinesort/domain/conversions.py.
    """
    total = 0
    for row in rows or []:
        rid = str(getattr(row, "row_id", "") or "")
        # Ce filtre doit rester EN AMONT de `_row_estimated_size` : depuis
        # #796 celui-ci parcourt l'arborescence (`_dir_tree_size`). Une row
        # ecartee ici ne declenche donc aucun `rglob` — ce qui compte pour un
        # film pose a la racine, dont le `folder` EST la racine de la
        # bibliotheque : la sommer reviendrait a facturer toute la
        # bibliotheque, en plus d'un parcours complet du disque par row.
        if rid not in approved_keys:
            continue
        total += _row_estimated_size(row)
    return total


def check_disk_space_for_apply(
    cfg: Any,
    rows: List[Any],
    approved_keys: set,
) -> Tuple[bool, Dict[str, Any]]:
    """Verifie qu'il y a assez d'espace libre sur le volume de destination.

    Retourne (ok, info) ou info contient :
      - free_bytes : espace libre actuel
      - needed_bytes : somme estimee + marge
      - estimated_bytes : somme brute (sans marge)
      - target_root : chemin verifie
      - message : explication FR pour l'UI

    Si l'estimation est nulle (rows vides ou stat echouees), on verifie
    seulement que le minimum absolu est respecte.
    """
    target_root = Path(getattr(cfg, "root", ".") or ".")
    try:
        usage = shutil.disk_usage(str(target_root))
    except (OSError, PermissionError) as exc:
        _logger.warning("disk_space_check: shutil.disk_usage echoue sur %s: %s", target_root, exc)
        # Si on ne peut meme pas lire l'espace, on laisse passer (mieux apply qui peut
        # echouer plus tard que blocage faux positif).
        return True, {
            "free_bytes": -1,
            "needed_bytes": 0,
            "estimated_bytes": 0,
            "target_root": str(target_root),
            "message": f"Impossible de lire l'espace disque sur {target_root}, pre-check ignore.",
        }

    estimated = estimate_apply_size(rows, approved_keys)
    needed = max(int(estimated * (1.0 + _SAFETY_MARGIN)), _MIN_FREE_BYTES)

    info = {
        "free_bytes": int(usage.free),
        "needed_bytes": int(needed),
        "estimated_bytes": int(estimated),
        "target_root": str(target_root),
    }

    if usage.free < needed:
        free_mb = usage.free / (1024 * 1024)
        needed_mb = needed / (1024 * 1024)
        info["message"] = (
            f"Espace disque insuffisant sur {target_root} : "
            f"{free_mb:.0f} Mo libres, {needed_mb:.0f} Mo necessaires "
            f"(somme estimee + 10% de marge). Liberez de l'espace "
            f"avant de lancer l'apply."
        )
        return False, info

    free_mb = usage.free / (1024 * 1024)
    needed_mb = needed / (1024 * 1024)
    info["message"] = f"Espace disque OK sur {target_root} : {free_mb:.0f} Mo libres, {needed_mb:.0f} Mo requis."
    return True, info
