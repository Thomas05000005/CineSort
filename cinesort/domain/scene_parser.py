"""Parser de noms de release scene (Phase 6.3).

Extrait un titre propre depuis un nom de fichier scene (BluRay rip, WEB-DL,
remux perso, etc.) en supprimant les tags techniques qui polluent la query
TMDb : release group, residus audio (DTS-HD MA, 5.1, 7.1), tags langue (FRENCH,
MULTi), labels d'edition (Director's Cut, Extended), etc.

Architecture :
- `parse_scene_title(filename)` : pipeline complet, retourne le titre nettoye
- Strategie position-aware : les tags ambigus (FRENCH, CUT, EDITION) ne sont
  stripes que APRES le token annee. Sinon "The French Connection 2" ou
  "The Final Cut" (1992) perdraient une partie de leur titre.

Pourquoi pas PTN (parse-torrent-name) ? Apres exploration :
- Install wheel echoue sur Windows sans PYTHONIOENCODING=utf-8 (CI risk)
- Year regex bridee a 2019 (films 2020+ pas detectes)
- Swap title/year sur films-annee (1917 -> title="2019", year=1917)
- Group field inclut l'extension (".mkv" colle au nom)
- Notre NOISE_RE existant couvre deja la majorite des tags ; 50 LOC additionnels
  suffisent pour atteindre le meme niveau de nettoyage sans nouvelle dep.

Backward compat : `clean_title_guess()` delegue ici, fallback regex actuelle
si parse_scene_title retourne une chaine vide ou trop courte.
"""

from __future__ import annotations

import re
from pathlib import Path

# --- Patterns -------------------------------------------------------------

# Tags techniques uniquement (resolution, codec, audio, source, profil).
# Volontairement SANS langue ni edition residue : ces tokens peuvent apparaitre
# dans des vrais titres ("The French Connection", "The Final Cut", "Theatre of
# Blood"). Ils sont stripes plus tard en mode end-anchored seulement.
_NOISE_RE = re.compile(
    r"""
    \b(
        2160p|1080p|720p|480p|360p|
        4k|uhd|fhd|
        hdr10\+?|hdr|dv|dolby[\s.-]?vision|sdr|
        bluray|blu[\s.-]?ray|brrip|bdrip|bd[\s.-]?remux|bd[\s.-]?rip|
        web[\s.-]?dl|web[\s.-]?rip|hdtv|hdrip|remux|dvdrip|cam|camrip|telesync|telecine|
        x265|x264|hevc|avc|xvid|divx|h\.?264|h\.?265|av1|vp9|
        truehd|dts[\s.-]?hd|dts[\s.-]?x|dts|atmos|aac|ac3|eac3|ddp|opus|flac|mp3|
        dd5\.?1|dd7\.?1|dd2\.?0|
        10bit|8bit|12bit|
        proper|repack|internal|limited|complete|hybrid|mhd|uhdrip|
        qtz|a3l|hdlight|4klight
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Tokens ambigus stripes UNIQUEMENT s'ils apparaissent apres le token annee.
# Strategie position-aware : "The French Connection 2 1975" -> "French" est
# AVANT 1975 donc preserve. "Le Capitaine Fracasse 1961 FRENCH" -> "FRENCH"
# est APRES 1961 donc stripe.
# Couvre langues + residus edition + sources ambigus (web, bd, br).
_AFTER_YEAR_NOISE = (
    r"(?:multi|truefrench|french|english|spanish|german|italian|"
    r"vff|vfq|vfi|vof|vf|vo|vostfr|vostr|vost|subfrench|dual|dubbed|"
    r"director'?s?|extended|theatrical|unrated|remastered|criterion|"
    r"edition|version|cut|special|imax|final|ultimate|"
    r"web|bd|br|tv|cam|tc|repack|proper)"
)

# Pattern : (annee)(tokens noise apres)*$ → on remplace par juste l'annee.
# Cas piege gere : "Blade Runner 2049 2017 Directors Cut" → regex va trouver
# "2017 Directors Cut" (2049 n'est pas suivi de noise donc skip), strip → "2049 2017".
_AFTER_YEAR_NOISE_RE = re.compile(
    r"(\b(?:19\d{2}|20\d{2})\b)(?:\s+" + _AFTER_YEAR_NOISE + r"\b)+\s*$",
    re.IGNORECASE,
)

# Release group : "-GROUPNAME" en fin de chaine.
# Requiert un espace AVANT le tiret pour ne pas casser "Spider-Man".
# 2-25 chars alphanum + _, evite de manger "Toy Story 4" -> "Toy Story" (le 4 n'a pas de tiret).
_RELEASE_GROUP_RE = re.compile(r"\s-\s*[A-Za-z0-9_]{2,25}\s*$")

# Residus audio : "DTS-HD MA", "DTS-HD HRA", "5.1", "7.1", "2.0", "Atmos".
# NOISE_RE catch "dts-hd" mais pas "ma" / "hra" standalone, et pas les channel counts.
_AUDIO_RESIDUE_RE = re.compile(
    r"\b(?:ma|hra|[257][\s.]?[01]|2[\s.]?0|atmos)\b",
    re.IGNORECASE,
)

# Year parenthesised : (2010), [2010], {2010}
_PAREN_YEAR_RE = re.compile(r"[\(\[\{]\s*(?:19\d{2}|20\d{2})\s*[\)\]\}]")

# Caracteres de garbage en fin de chaine apres nettoyage
_TRAILING_GARBAGE_RE = re.compile(r"[\s\-_\.]+$")


def parse_scene_title(filename: str) -> str:
    """Extrait un titre nettoye depuis un nom de fichier scene.

    Pipeline (ordre important) :
    1. Strip extension + remplace separateurs (`.` `_` -> espace)
    2. Strip parenthesized year (retire avant que les hyphens deviennent ambigus)
    3. NOISE_RE.sub : retire ~50 tags techniques (codec, resolution, audio, ...)
       AVANT le strip release group, pour qu'apres avoir supprime "Atmos" /
       "x265" / etc., le release group "-XXXX" se retrouve isole avec un
       espace avant le tiret (matchable par _RELEASE_GROUP_RE).
    4. Audio residue : "HD MA", "5.1", "7.1"
    5. Collapse intermediaire whitespace
    6. Strip release group `-XXXXX$`
    7. Position-aware strip : tags ambigus (FRENCH, CUT, EDITION, WEB) stripes
       UNIQUEMENT s'ils apparaissent apres le token annee. "The French
       Connection 2 1975" preserve "French" (avant l'annee) ; "Le Ruffian 1961
       FRENCH" strip "FRENCH" (apres l'annee).
    8. Final cleanup, strip edges

    Note : l'annee n'est PAS stripee. Downstream (`build_candidates_from_name`,
    `_title_similarity`) tolere l'annee dans le titre et l'utilise comme indice.
    Stripper l'annee ici casserait les films-annee (1917, 2001 Space Odyssey,
    Blade Runner 2049).

    Args:
        filename: Nom de fichier brut, avec ou sans extension.

    Returns:
        Titre nettoye. Chaine vide si filename est vide.
    """
    if not filename:
        return ""

    # 1. Strip extension + separateurs
    # Note : Path(".mkv").stem retourne ".mkv" (cas hidden file). On filtre ce
    # cas degenere en cherchant "." final pour traiter comme une extension.
    p = Path(filename)
    name = p.stem if p.suffix else p.name
    if name.startswith("."):
        # Cas pathologique ".mkv" / ".mp4" - retour vide
        return ""
    name = name.replace(".", " ").replace("_", " ")

    # 2. Position-aware strip si annee parenthesee : strip aussi le suffixe
    # "(year) LANG" → garde uniquement le titre avant la parenthese.
    # Sinon "Le Capitaine Fracasse (1961) FRENCH" -> "Le Capitaine Fracasse FRENCH".
    paren_year_match = _PAREN_YEAR_RE.search(name)
    if paren_year_match:
        name = name[: paren_year_match.start()].rstrip(" .-_")

    # 3. Strip noise tags AVANT release group : NOISE_RE retire les tags
    # adjacents au groupe (codec, audio), ce qui isole "-XXXX" en fin de chaine
    # avec un espace avant — matchable par _RELEASE_GROUP_RE.
    name = _NOISE_RE.sub(" ", name)

    # 4. Strip audio residue
    name = _AUDIO_RESIDUE_RE.sub(" ", name)

    # 5. Collapse intermediaire (pour que _RELEASE_GROUP_RE matche " -GROUP" propre)
    name = re.sub(r"\s+", " ", name).strip()

    # 6. Strip release group
    name = _RELEASE_GROUP_RE.sub(" ", name)

    # 7. Position-aware : strip langues + residus edition + sources ambigus
    # UNIQUEMENT apres le token annee. Preserve les vrais titres ("The French
    # Connection 2", "The Final Cut").
    name = _AFTER_YEAR_NOISE_RE.sub(r"\1", name)

    # 8. Final cleanup
    name = re.sub(r"\s+", " ", name)
    name = _TRAILING_GARBAGE_RE.sub("", name)
    return name.strip(" -_.")
