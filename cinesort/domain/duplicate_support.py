from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# VQ-1 : import top-level desormais sur. La chaine
# duplicate_support -> naming -> path_utils est un DAG (path_utils est une
# feuille), plus de cycle vers core. build_naming_context / format_movie_folder
# viennent du MEME module `naming` (aucun nouveau cycle) et alignent
# planned_target_folder sur apply_core.apply_single (MEDI-28). _normalize_iso639
# est une feuille domaine (subtitle_helpers, stdlib only) reutilisee pour
# reconcilier les 'subtitle_missing_<lang>' cote serialisation (MEDI-31).
from cinesort.domain.naming import (
    build_naming_context as _build_naming_context,
    folder_matches_template as _folder_matches_template,
    format_movie_folder as _format_movie_folder,
)
from cinesort.domain.subtitle_helpers import _normalize_iso639
from cinesort.domain.title_helpers import strip_trailing_year_if_equal as _strip_trailing_year_if_equal

_MOVIE_DIR_RE = re.compile(r"^\s*(?P<title>.+?)\s*\((?P<year>19\d{2}|20\d{2})\)\s*$")


def is_under_collection_root(
    cfg: Any,
    folder: Path,
    *,
    norm_win_path: Callable[[Path], Any],
) -> bool:
    folder_pw = norm_win_path(folder)
    root_pw = norm_win_path(cfg.root)
    try:
        rel = folder_pw.relative_to(root_pw)
    except (ValueError, TypeError):
        return False
    parts = [part.lower() for part in rel.parts]
    return len(parts) >= 1 and parts[0] == str(cfg.collection_root_name or "").lower()


def movie_dir_title_year(name: str) -> Optional[Tuple[str, int]]:
    match = _MOVIE_DIR_RE.match(name or "")
    if not match:
        return None
    title = (match.group("title") or "").strip()
    year = int(match.group("year"))
    if not title:
        return None
    return title, year


def movie_key(
    title: str,
    year: int,
    *,
    norm_for_tokens: Callable[[str], str],
    edition: Optional[str] = None,
) -> str:
    normalized_year = int(year or 0)
    # LOTD-DUP-TITLE-YEAR (revue round 1) : sans TMDb, "Titre 2005"|2005 (nom
    # "Titre.2005.720p") et "Titre"|2005 (dossier "Titre (2005)") sont le MEME
    # film -> on strippe l'annee de queue == annee du couple AVANT de tokeniser,
    # pour qu'ils partagent la cle. Le film-annee "Blade Runner 2049"|2017 garde
    # son titre (2049 != 2017). Normalisation de cle SEULEMENT, jamais le renommage.
    key_title = _strip_trailing_year_if_equal(title, normalized_year)
    base = f"{norm_for_tokens(key_title)}|{normalized_year}"
    ed = (edition or "").strip().lower()
    if ed:
        return f"{base}|{ed}"
    return base


def single_folder_is_conform(
    folder_name: str,
    title: str,
    year: int,
    *,
    windows_safe: Callable[[str], str],
    norm_for_tokens: Callable[[str], str],
    movie_dir_title_year: Callable[[str], Optional[Tuple[str, int]]],
    naming_template: str = "",
) -> bool:
    # Check 1 : template actif (si fourni)
    if naming_template:
        # VQ-1 : ancien lazy import remplace par alias top-level
        # `_folder_matches_template` (cycle casse via path_utils).
        if _folder_matches_template(folder_name, naming_template, title, year):
            return True

    # Check 1bis : defense en profondeur — equivalence FS Windows/SMB.
    # os.listdir peut retourner NFD (macOS/SMB) alors que windows_safe applique
    # NFC cote template. La comparaison via _norm_compare (lower+collapse spaces)
    # ne couvre pas NFC vs NFD car les bytes different meme apres lower().
    # Cette verification capture aussi les cas ou Check 1 echoue parce que le
    # template est vide ou ou movie_dir_title_year ne match pas mais le folder
    # est en fait equivalent au format "Title (Year)" attendu.
    if 1900 <= int(year or 0) <= 2100:
        expected_folder = windows_safe(f"{title or ''} ({int(year)})")
        try:
            norm_folder = unicodedata.normalize("NFC", folder_name or "").casefold()
            norm_expected = unicodedata.normalize("NFC", expected_folder).casefold()
            if norm_folder == norm_expected:
                return True
        except (TypeError, ValueError):
            pass

    # Check 2 : fallback format historique "Title (Year)"
    expected_title = windows_safe(title or "")
    if 1900 <= int(year or 0) <= 2100:
        current = movie_dir_title_year(folder_name)
        if not current:
            return False
        current_title, current_year = current
        return int(current_year) == int(year) and (norm_for_tokens(current_title) == norm_for_tokens(expected_title))
    return norm_for_tokens(folder_name) == norm_for_tokens(expected_title)


def find_video_case_insensitive(folder: Path, video_name: str) -> Optional[Path]:
    candidate = folder / video_name
    if candidate.exists():
        return candidate
    try:
        for child in folder.iterdir():
            if child.is_file() and child.name.lower() == str(video_name or "").lower():
                return child
    except (OSError, PermissionError, FileNotFoundError):
        return None
    return None


def planned_target_folder(
    cfg: Any,
    row: Any,
    title: str,
    year: int,
    *,
    is_under_collection_root: Callable[[Any, Path], bool],
    windows_safe: Callable[[str], str],
) -> Path:
    # AUDIT 2026-07-13 (MEDI-28) : la cible PLANIFIEE affichee/consommee par
    # l'ecran Doublons doit etre STRICTEMENT celle qu'apply_core ecrira, sinon
    # (a) les chemins 'target' exposes sont faux, (b) has_plan_dupe/plan_conflict
    # deviennent des FAUX NEGATIFS (deux copies d'une meme saga visent le MEME
    # <root>/<_Collection>/<saga>/<nom> a l'apply mais des parents differents ici
    # -> collision reelle non signalee), (c) can_merge_single est evalue contre
    # un dossier qui n'est pas la vraie cible. On MIROITE donc apply_single
    # (apply_core.py:2101-2118) : meme template + edition + separator, et la meme
    # redirection saga _Collection. build_naming_context+format_movie_folder
    # garantissent planned == apply par CONSTRUCTION (memes entrees, memes fns).
    folder_name = _format_movie_folder(
        cfg.naming_movie_template,
        _build_naming_context(
            title=title,
            year=year,
            edition=str(getattr(row, "edition", "") or ""),
            separator=getattr(cfg, "separator", " "),
        ),
    )
    if row.kind == "single":
        # Miroir de apply_single:2112-2118 : une saga TMDb + collections activees
        # redirige le single vers <root>/<collection_root>/<saga>/<nom>.
        coll_name = str(getattr(row, "tmdb_collection_name", "") or "").strip()
        if coll_name and cfg.enable_collection_folder:
            return cfg.root / cfg.collection_root_name / windows_safe(coll_name) / folder_name
        return Path(row.folder).parent / folder_name

    col_folder = Path(row.folder)
    if cfg.enable_collection_folder and (not is_under_collection_root(cfg, col_folder)):
        col_folder = cfg.root / cfg.collection_root_name / windows_safe(col_folder.name)
    return col_folder / folder_name


def existing_movie_folder_index(
    cfg: Any,
    *,
    movie_dir_title_year: Callable[[str], Optional[Tuple[str, int]]],
    movie_key: Callable[[str, int], str],
) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}

    def _dirs(path: Path) -> List[Path]:
        try:
            return [child for child in path.iterdir() if child.is_dir()]
        except (OSError, PermissionError, FileNotFoundError):
            return []

    def _index(path: Path) -> None:
        pair = movie_dir_title_year(path.name)
        if not pair:
            return
        title, year = pair
        out.setdefault(movie_key(title, year), []).append(str(path))

    try:
        level1 = [path for path in cfg.root.iterdir() if path.is_dir()]
    except (OSError, PermissionError, FileNotFoundError):
        return out

    # F18 : le dossier collections est un CONTENEUR TRANSPARENT. La cible reelle
    # d'un single-saga est <root>/<collection_root>/<saga>/<Titre (Annee)>
    # (planned_target_folder L160-171, miroir apply_core.py:2113) soit une
    # profondeur 3, alors que la boucle historique (a) skippait tout dossier
    # niveau-1 prefixe '_' — dont '_Collection' par defaut — et (b) n'indexait
    # que 2 niveaux. Une copie deja rangee sous sa saga etait donc invisible du
    # detecteur, la collision n'emergeant qu'a l'apply (merge_dir_safe).
    # On teste le nom du dossier collections AVANT le skip '_' pour couvrir
    # aussi un collection_root_name configure sans underscore.
    #
    # F18 (revue R1) : la transparence n'est valable que si la fonctionnalite
    # collections est ACTIVE. Sinon planned_target_folder (L164/L169) ne vise
    # JAMAIS <root>/<collection_root>/... et le dossier redevient ce que le
    # commentaire ci-dessous decrit : un bucket interne CineSort, saute par le
    # scan (scan_helpers.py:311, skip inconditionnel) et contenant de vraies
    # copies parquees -> l'indexer fabrique des conflits fantomes (groupes a 1
    # row citant une cible que rien ne planifie).
    coll_root = str(getattr(cfg, "collection_root_name", "") or "").strip().lower()
    collections_active = bool(getattr(cfg, "enable_collection_folder", False))
    for level1_dir in level1:
        name = level1_dir.name.lower()
        if coll_root and collections_active and name == coll_root:
            # Les sagas deviennent les "level1" -> la profondeur 3 est couverte.
            containers = _dirs(level1_dir)
        elif name.startswith("_"):
            # _review / _Vide / _Conflicts / _Dossier Nettoyage restent exclus :
            # ils contiennent de VRAIES copies mises de cote, les indexer
            # creerait des conflits fantomes.
            continue
        else:
            containers = [level1_dir]

        for container in containers:
            _index(container)
            for child in _dirs(container):
                _index(child)
    return out


def _check_file_collisions(
    src_files: List[Path],
    *,
    dst_for: Callable[[Path], Path],
    files_identical_quick: Callable[[Path, Path], bool],
) -> Tuple[bool, str]:
    for src in src_files:
        dst = dst_for(src)
        if not dst.exists():
            continue
        if not dst.is_file():
            return False, f"collision path type mismatch: {dst}"
        if files_identical_quick(src, dst):
            continue
        return False, f"file collision not resolvable: {dst.name}"
    return True, "target folder exists; merge will be performed safely"


def can_merge_single_without_blocking(
    cfg: Any,
    src_dir: Path,
    dst_dir: Path,
    *,
    is_managed_merge_file: Callable[[Any, Path], bool],
    files_identical_quick: Callable[[Path, Path], bool],
) -> Tuple[bool, str]:
    if not dst_dir.exists():
        return True, "target folder absent"
    if not dst_dir.is_dir():
        return False, "target exists and is not a folder"
    if not src_dir.exists() or not src_dir.is_dir():
        return False, "source folder missing"

    try:
        files = [path for path in src_dir.rglob("*") if path.is_file() and is_managed_merge_file(cfg, path)]
    except (OSError, PermissionError, FileNotFoundError):
        return False, "source folder not readable"

    return _check_file_collisions(
        files,
        dst_for=lambda src: dst_dir / src.relative_to(src_dir),
        files_identical_quick=files_identical_quick,
    )


def can_merge_collection_item_without_blocking(
    cfg: Any,
    row: Any,
    target_dir: Path,
    *,
    find_video_case_insensitive: Callable[[Path, str], Optional[Path]],
    classify_sidecars: Callable[[Any, Path, Path], List[Path]],
    files_identical_quick: Callable[[Path, Path], bool],
) -> Tuple[bool, str]:
    if not target_dir.exists():
        return True, "target folder absent"
    if not target_dir.is_dir():
        return False, "target exists and is not a folder"

    folder = Path(row.folder)
    if not folder.exists():
        return False, "source collection folder missing"

    video = find_video_case_insensitive(folder, row.video)
    if not video:
        return False, "source video missing"

    src_files = [video]
    try:
        src_files.extend(classify_sidecars(cfg, folder, video))
    except (OSError, PermissionError, FileNotFoundError):
        return False, "source sidecars unreadable"

    return _check_file_collisions(
        src_files,
        dst_for=lambda src: target_dir / src.name,
        files_identical_quick=files_identical_quick,
    )


def _reconciled_row_flags(row: Any) -> List[str]:
    """warning_flags 'humanisables' pour la section Alertes de l'ecran Doublons.

    MEDI-31 : doublons.js agrege `row.warning_flags` pour la carte doublon et
    l'inspecteur, mais le payload de check_duplicates n'exposait pas ce champ ->
    section Alertes TOUJOURS vide. On serialise ici les flags RECONCILIES (pas
    bruts), miroir DOMAIN-PUR de ui.api.run_read_support.reconcile_subtitle_flags :
    un 'subtitle_missing_<lang>' dont la langue est en fait presente parmi les
    sous-titres externes connus de la row (PlanRow.subtitle_languages) est un faux
    positif -> retire ; tout autre flag (integrity_header_invalid, nfo_*,
    not_a_movie, subtitle_orphan...) est conserve a l'identique. La row est
    PARTAGEE (endpoint de LECTURE, cf. H12 / test_duplicates_no_row_mutation_v77)
    -> on construit une liste NEUVE, aucune mutation de row.warning_flags.

    Limite assumee : les pistes EMBARQUEES (quality_reports.metrics.
    subtitles_embedded) ne sont pas accessibles a cette couche (aucun store injecte
    dans find_duplicate_targets) ; un faux 'subtitle_missing_fr' du a du FR MUXE
    n'est donc pas reconciliable ici. Il l'est deja sur les ecrans Verification /
    Bibliotheque qui, eux, ont le quality_report.
    """
    present: set = set()
    for lang in (getattr(row, "subtitle_languages", None) or []):
        norm = _normalize_iso639(str(lang)) or str(lang).strip().lower()
        if norm:
            present.add(norm)
    out: List[str] = []
    for flag in (getattr(row, "warning_flags", None) or []):
        text = str(flag)
        if text.startswith("subtitle_missing_"):
            raw = text[len("subtitle_missing_"):].strip().lower()
            lang = _normalize_iso639(raw) or raw
            if lang and lang in present:
                continue  # faux positif : la langue EST presente -> drop
        out.append(text)
    return out


def _template_varies_by_edition(template: str) -> bool:
    """True si le nom de dossier film produit par `template` change selon l'edition.

    AUDIT 2026-07-15 (H11) : la cle d'identite de groupement (find_duplicate_targets)
    doit inclure l'edition SSI le dossier REELLEMENT produit par planned_target_folder
    la contient. Avec le template par defaut "{title} ({year})", l'edition N'APPARAIT
    PAS dans le nom de dossier -> (a) deux editions du meme film visent le MEME dossier
    (vrai conflit) et (b) un dossier existant "Titre (Annee)" — indexe SANS edition par
    existing_movie_folder_index (movie_dir_title_year ne parse que ce format) — ne
    matchait plus la cle (detection "cible deja existante" MORTE pour toute row avec
    edition). Inversement, un template qui encode l'edition ({edition}, {edition-tag},
    variantes crochets...) produit des dossiers SEPARES -> la cle DOIT inclure l'edition
    pour ne pas fusionner a tort deux editions distinctes.

    On derive le flag de la MEME chaine de rendu que planned_target_folder
    (build_naming_context + format_movie_folder) : on rend le template avec une
    edition non vide puis vide (title/year neutres) et on compare. Coherent PAR
    CONSTRUCTION, robuste a toute variable d'edition presente/future, aucune
    heuristique de sous-chaine fragile.
    """
    with_edition = _format_movie_folder(
        template, _build_naming_context(title="Film", year=2000, edition="Edition")
    )
    without_edition = _format_movie_folder(
        template, _build_naming_context(title="Film", year=2000, edition="")
    )
    return with_edition != without_edition


def find_duplicate_targets(
    cfg: Any,
    rows: List[Any],
    decisions: Dict[str, Dict[str, object]],
    *,
    max_groups: int = 120,
    existing_movie_folder_index: Callable[[Any], Dict[str, List[str]]],
    movie_key: Callable[[str, int], str],
    planned_target_folder: Callable[[Any, Any, str, int], Path],
    norm_win_path: Callable[[Path], str],
    can_merge_single_without_blocking: Callable[[Any, Path, Path], tuple[bool, str]],
    can_merge_collection_item_without_blocking: Callable[[Any, Any, Path], tuple[bool, str]],
    windows_safe: Callable[[str], str],
) -> Dict[str, object]:
    existing_idx = existing_movie_folder_index(cfg)
    planned_idx: Dict[str, List[Dict[str, str]]] = {}
    rows_by_id = {row.row_id: row for row in rows}
    total_checked = 0

    # H11 : l'edition n'entre dans la cle d'identite que si le dossier produit
    # par le template la porte (sinon la cle diverge de existing_movie_folder_index
    # qui indexe "Titre (Annee)" SANS edition -> detection cible-existante morte,
    # et deux editions visant le meme dossier ne sont plus vues comme un conflit).
    template_uses_edition = _template_varies_by_edition(
        str(getattr(cfg, "naming_movie_template", "") or "")
    )

    for row in rows:
        dec = decisions.get(row.row_id, {})
        if not bool(dec.get("ok", False)):
            continue

        # AUDIT 2026-06-14 (R6-A) : un episode TV n'est PAS un doublon de film.
        # Plusieurs episodes d'une serie partagent le meme titre+annee mais sont
        # des fichiers distincts -> l'ancienne branche "collection" les groupait
        # a tort (ex: dossier "A Knight ..." = 6 tv_episode). Choix utilisateur
        # "1 liste par identite" : on exclut les episodes de la detection.
        if getattr(row, "kind", "") == "tv_episode":
            continue

        title = str(dec.get("title") or row.proposed_title).strip() or row.proposed_title
        try:
            year = int(dec.get("year") or row.proposed_year)
        except (ValueError, TypeError):
            year = int(row.proposed_year or 0)
        # Fix bug TV series / BONUS Star Wars : ne plus skip silencieusement les
        # rows avec year invalide. On regroupe alors sur un movie_key construit
        # sur le title seul (year=0 -> norme via movie_key).
        #
        # AUDIT 2026-07-13 (H12) : NE JAMAIS muter row.warning_flags ici.
        # check_duplicates est un endpoint de LECTURE et les PlanRow sont
        # PARTAGES (run_flow_support : `rows = rs.rows`, la meme liste memoire
        # que get_plan / get_dashboard). Ecrire 'year_missing' polluait
        # durablement les warning_flags -> le KPI 'Conflits' (_CONFLICT_FLAGS)
        # gonflait selon l'ordre de visite des ecrans et is_auto_approvable_flags
        # basculait. On calcule year_invalid LOCALEMENT (year=0 pour la seule
        # decision de doublon) sans toucher l'objet partage.
        year_invalid = not (1900 <= year <= 2100)
        if year_invalid:
            year = 0

        total_checked += 1
        row_edition = getattr(row, "edition", None) if template_uses_edition else None
        key = movie_key(title, year, edition=row_edition)
        target = planned_target_folder(cfg, row, title, year)
        planned_idx.setdefault(key, []).append(
            {
                "row_id": row.row_id,
                "kind": row.kind,
                "title": windows_safe(title),
                "year": str(year),
                "target": str(target),
                "source_folder": str(row.folder),
                # R6-A : racine d'origine (multi-root) pour etiqueter la portee.
                "source_root": str(getattr(row, "source_root", None) or ""),
                # MEDI-31 : alimente la section Alertes de l'ecran Doublons
                # (doublons.js allFlags/labelsForFlags). Additif (apply ne lit que
                # row_id/kind/target/source_folder) ; flags RECONCILIES, jamais bruts.
                "warning_flags": _reconciled_row_flags(row),
            }
        )

    groups: List[Dict[str, object]] = []
    mergeables: List[Dict[str, object]] = []
    for key, items in planned_idx.items():
        year = int(items[0]["year"])
        title = str(items[0]["title"])
        existing_paths = existing_idx.get(key, [])
        plan_targets = [item["target"] for item in items]

        # F22 : la collision de destination se juge sur des chemins NORMALISES.
        # NTFS est insensible a la casse et movie_key groupe deja en lower ->
        # '...\\SEVEN (1995)' et '...\\Seven (1995)' sont le MEME dossier, mais
        # la comparaison de chaines BRUTES les voyait distincts (plan_conflict
        # faux negatif). norm_win_path rend un PureWindowsPath dont l'egalite et
        # le hash sont insensibles a la casse MEME sous Linux/CI.
        normalized_targets = []
        for target in plan_targets:
            try:
                normalized_targets.append(norm_win_path(Path(target)))
            except (ValueError, TypeError, OSError):
                # Degradation sure : on retombe sur la comparaison brute pour ce
                # seul chemin plutot que de faire echouer check_duplicates.
                normalized_targets.append(str(target))

        has_plan_dupe = len(set(normalized_targets)) < len(normalized_targets)
        existing_elsewhere = []
        target_norms = set(normalized_targets)
        # REGRESSION M8 (relecture B2) : depuis la redirection saga, la cible d'un
        # single-saga (<root>/<_Collection>/<saga>/<nom>) DIVERGE de son dossier
        # SOURCE deja conforme (<root>/<nom>). existing_movie_folder_index indexe
        # cette source ; sans exclusion, matched_target reste False et la source
        # PROPRE du film relocalise tombait dans existing_elsewhere -> faux groupe
        # a 1 item citant sa propre source. On exclut donc les dossiers SOURCE des
        # items en cours de relocalisation (generalise same_current_single au cas
        # source==existing quand la cible a change). Un VRAI 2e exemplaire (autre
        # dossier, hors source) reste detecte : seul le chemin source est retire.
        source_norms = set()
        for item in items:
            try:
                source_norms.add(norm_win_path(Path(item["source_folder"])))
            except (ValueError, TypeError, OSError):
                continue
        for existing_path in existing_paths:
            try:
                existing_norm = norm_win_path(Path(existing_path))
            except (ValueError, TypeError, OSError):
                continue

            matched_target = False
            conflict = False
            for item in items:
                try:
                    target_norm = norm_win_path(Path(item["target"]))
                    source_norm = norm_win_path(Path(item["source_folder"]))
                except (ValueError, TypeError, OSError):
                    continue
                if existing_norm != target_norm:
                    continue
                matched_target = True
                same_current_single = (str(item.get("kind") or "") == "single") and (source_norm == target_norm)
                if not same_current_single:
                    row_obj = rows_by_id.get(str(item.get("row_id") or ""))
                    mergeable = False
                    reason = "target folder exists"
                    if row_obj is not None:
                        if row_obj.kind == "single":
                            mergeable, reason = can_merge_single_without_blocking(
                                cfg,
                                Path(row_obj.folder),
                                Path(item["target"]),
                            )
                        else:
                            mergeable, reason = can_merge_collection_item_without_blocking(
                                cfg,
                                row_obj,
                                Path(item["target"]),
                            )
                    if mergeable:
                        mergeables.append(
                            {
                                "title": title,
                                "year": year,
                                "row_id": str(item.get("row_id") or ""),
                                "kind": "mergeable",
                                "mergeable": True,
                                "reason": reason,
                                "target": str(item["target"]),
                                "source_folder": str(item["source_folder"]),
                            }
                        )
                    else:
                        conflict = True
                break

            if conflict or (
                (not matched_target)
                and existing_norm not in target_norms
                and existing_norm not in source_norms
            ):
                existing_elsewhere.append(existing_path)

        # AUDIT 2026-06-14 (R6-A) : "1 liste par identite". On emet un groupe des
        # qu'au moins 2 films partagent la meme identite (titre+annee), MEME si
        # leurs dossiers de destination different (doublons cross-racine que
        # l'ancienne condition has_plan_dupe ratait -> "65 detectes / 5
        # affiches"). La collision de destination reste un signal interne
        # (plan_conflict) pour la securite d'apply.
        identity_dupe = len(items) >= 2
        if (not identity_dupe) and (not existing_elsewhere):
            continue

        # Portee du doublon (badge informatif, la liste reste unique) :
        #  - cross_root : copies dans des racines differentes (source_root) ;
        #  - same_root  : meme racine mais dossiers parents differents ;
        #  - same_folder: meme dossier parent.
        roots = {str(it.get("source_root") or "").strip() for it in items}
        roots.discard("")
        parents = set()
        for it in items:
            try:
                parents.add(norm_win_path(Path(it["source_folder"]).parent))
            except (ValueError, TypeError, OSError):
                pass
        if len(roots) > 1:
            scope = "cross_root"
        elif len(parents) > 1:
            scope = "same_root"
        else:
            scope = "same_folder"

        groups.append(
            {
                "title": title,
                "year": year,
                "rows": items,
                "existing_paths": existing_elsewhere[:8],
                "plan_conflict": bool(has_plan_dupe),
                "scope": scope,
            }
        )
        if len(groups) >= max_groups:
            break

    return {
        "checked_rows": total_checked,
        "total_groups": len(groups),
        "groups": groups,
        "mergeable_count": len(mergeables),
        "mergeables": mergeables[:200],
    }
