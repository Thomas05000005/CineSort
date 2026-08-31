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
from typing import Optional

# --- Patterns -------------------------------------------------------------

# Provider tags (Plex/Jellyfin/Radarr/TRaSH) inseres par l'utilisateur dans
# les noms de dossier/fichier pour forcer un auto-link deterministe au scan.
# Formats supportes : {tmdb-12345}, [tmdb-12345], [tmdbid-12345], {tmdb:12345},
#                     [imdbid-tt1234567], {imdb-tt1234567}, [imdb:tt1234567].
# Fix B02-TAGS-BRACKETS : avant ce fix, les chiffres TMDb (ex 27205) restaient
# dans le titre nettoye et polluaient la query fuzzy. parse_scene_title() doit
# strip ces tags AVANT le pipeline noise/year/release-group.
#
# SOURCE UNIQUE (fix ultra-audit 2026-08-31, #9). Ces deux motifs existaient en
# TROIS exemplaires -- ici, `naming.py:25` et `title_helpers.py:30` -- et les
# trois annoncaient dans leur commentaire tolerer les espaces internes. Un seul
# le faisait : celui de `naming.py`, qui porte le `\s*` avant le separateur.
# Mesure sur « Inception (2010) {tmdb - 27205} » : `naming` extrayait 27205,
# `title_helpers` et ce module rendaient None, et `strip_provider_tags` laissait
# le tag entier dans le titre -- donc les chiffres TMDb partaient en query
# fuzzy, ce que ce fix B02 existe precisement pour empecher. La variante la plus
# permissive (celle qui tient la promesse des trois commentaires) est retenue,
# et ce module -- feuille sans aucun import interne -- en est le seul porteur.
_PROVIDER_TMDB_TAG_RE = re.compile(
    r"[\{\[]\s*tmdb(?:id)?\s*[\-:_]\s*(\d{1,9})\s*[\}\]]",
    re.IGNORECASE,
)
_PROVIDER_IMDB_TAG_RE = re.compile(
    r"[\{\[]\s*imdb(?:id)?\s*[\-:_]\s*(tt\d{7,10})\s*[\}\]]",
    re.IGNORECASE,
)


def strip_provider_tags(name: str) -> str:
    """Retire les tags providers (TMDb/IMDb) inseres dans un nom de fichier/dossier.

    Les tags `{tmdb-XXX}` / `[imdbid-ttXXX]` sont inseres par les conventions
    Plex/Jellyfin/Radarr/TRaSH pour forcer un auto-link deterministe. Ils ne
    doivent pas se retrouver dans le titre nettoye envoye en query fuzzy TMDb,
    sinon les chiffres TMDb peuvent etre confondus avec des annees ou polluer
    la similarite.

    Examples:
        >>> strip_provider_tags("Inception (2010) {tmdb-27205}")
        'Inception (2010)'
        >>> strip_provider_tags("Fight Club [tmdb-550] [imdbid-tt0137523]")
        'Fight Club'
        >>> strip_provider_tags("The Matrix (1999) [imdb:tt0133093]")
        'The Matrix (1999)'

    Args:
        name: Nom brut de dossier ou fichier (avec ou sans extension).

    Returns:
        Le nom sans les brackets/braces provider, whitespace collapse.
    """
    if not name:
        return ""
    cleaned = _PROVIDER_TMDB_TAG_RE.sub(" ", name)
    cleaned = _PROVIDER_IMDB_TAG_RE.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def extract_provider_tags(name: str) -> tuple[Optional[int], Optional[str]]:
    """Extrait les ids providers (tmdb_id, imdb_id) depuis un nom.

    Retourne `(None, None)` si rien trouve. Le tmdb_id est cast en `int`, le
    imdb_id est normalise en lowercase (`tt0133093`).

    Examples:
        >>> extract_provider_tags("Inception (2010) {tmdb-27205}")
        (27205, None)
        >>> extract_provider_tags("Fight Club [tmdb-550] [imdbid-tt0137523]")
        (550, 'tt0137523')
        >>> extract_provider_tags("Inception (2010)")
        (None, None)

    Args:
        name: Nom brut de dossier ou fichier.

    Returns:
        Tuple `(tmdb_id, imdb_id)`. Composants `None` si non extractibles.
    """
    if not name:
        return (None, None)
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    m = _PROVIDER_TMDB_TAG_RE.search(name)
    if m:
        try:
            tmdb_id = int(m.group(1))
        except (ValueError, TypeError):
            tmdb_id = None
    m = _PROVIDER_IMDB_TAG_RE.search(name)
    if m:
        imdb_id = m.group(1).lower()
    return (tmdb_id, imdb_id)


# Tags techniques uniquement (resolution, codec, audio, source, profil).
# Volontairement SANS langue ni edition residue : ces tokens peuvent apparaitre
# dans des vrais titres ("The French Connection", "The Final Cut", "Theatre of
# Blood"). Ils sont stripes plus tard en mode end-anchored seulement.
# BUG-TITLE-CHANNEL-RESIDUE (Lot D 2026-07) : `h[\s.]?26[45]` au lieu de
# `h\.?26[45]` — le `\.?` etait mort car les points sont deja remplaces par des
# espaces avant le sub ; "H.265-EVO" devenait "H 265-EVO" jamais nettoye (meme
# famille de residu colle au groupe que "7.1-GRP").
_NOISE_RE = re.compile(
    r"""
    \b(
        2160p|1080p|720p|480p|360p|
        4k|uhd|fhd|
        hdr10\+?|hdr|dv|dolby[\s.-]?vision|sdr|
        bluray|blu[\s.-]?ray|brrip|bdrip|bd[\s.-]?remux|bd[\s.-]?rip|
        web[\s.-]?dl|web[\s.-]?rip|hdtv|hdrip|remux|dvdrip|camrip|telesync|telecine|
        x265|x264|hevc|avc|xvid|divx|h[\s.]?26[45]|av1|vp9|
        truehd|dts[\s.-]?hd|dts[\s.-]?x|dts|atmos|aac|ac3|eac3|ddp|flac|mp3|
        dd5\.?1|dd7\.?1|dd2\.?0|
        10bit|8bit|12bit|
        repack|mhd|uhdrip|
        qtz|a3l|hdlight|4klight
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Tokens ambigus stripes UNIQUEMENT s'ils apparaissent apres le token annee.
#
# ATTENTION A L'ORDRE : `_NOISE_RE` (etape 3) s'execute QUATRE etapes avant
# ce traitement (etape 7). Un jeton present dans les deux listes est donc
# consomme par la premiere et n'atteint JAMAIS celle-ci — c'etait le cas de
# `cam`, `proper` et `repack`, inscrits ici mais inatteignables. Ajouter un
# jeton ci-dessous SANS le retirer de `_NOISE_RE` ne fait rien du tout.
# Strategie position-aware : "The French Connection 2 1975" -> "French" est
# AVANT 1975 donc preserve. "Le Capitaine Fracasse 1961 FRENCH" -> "FRENCH"
# est APRES 1961 donc stripe.
# Couvre langues + residus edition + sources ambigus (web, bd, br).
_AFTER_YEAR_NOISE = (
    r"(?:multi|truefrench|french|english|spanish|german|italian|"
    r"vff|vfq|vfi|vof|vf|vo|vostfr|vostr|vost|subfrench|dual|dubbed|"
    r"director'?s?|extended|theatrical|unrated|remastered|restored|"
    r"criterion|edition|version|cut|special|imax|final|ultimate|"
    r"hdlight|4klight|hdr|hdr10\+?|sdr|uhd|"
    # UN JETON, UNE LISTE. `cam`, `proper` et `repack` vivaient ici ET dans
    # `_NOISE_RE` — qui s'execute quatre etapes plus tot et les consommait, si
    # bien que leur presence ici ne faisait rien. Les jetons AMBIGUS sont
    # desormais traites au seul endroit ou ils peuvent l'etre correctement :
    # `_TRAILING_AMBIGU_RE`, qui sait distinguer « le jeton SUIT quelque chose »
    # de « le jeton EST tout le nom ».
    #
    # Une redondance ici serait indetectable : les deux motifs sont ancres sur
    # `$` et le trailing est strictement plus permissif (il n'exige pas
    # d'annee). C'est un mutant SURVIVANT qui l'a etabli — le mutant ne disait
    # pas « ton test est faible », il disait « ce code ne sert a rien ».
    r"web|bd|br|tv|tc)"
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
# AUDIT 2026-06-11 (R4-P2) : le tiret doit etre COLLE au groupe (pas de \s* apres).
# Signal structurel scene : "x264-DEiTY" laisse " -DEiTY" apres le strip noise
# (tiret colle), alors qu'un sous-titre legitime " - Ragnarok" a un espace des
# DEUX cotes. L'ancien \s* permettait a "Thor - Ragnarok 4K" (had_tech_marker
# via 4K) de perdre " - Ragnarok". Trade-off assume : un groupe P2P exotique
# " - GROUP" (espace apres tiret, rare) n'est plus strippe — preferer un residu
# dans le titre a un titre ampute.
_RELEASE_GROUP_RE = re.compile(r"\s-[A-Za-z0-9_]{2,25}\s*$")

# Tags langue trailing sans annee prealable. Couvre les cas type
# "L'arme Fatale 2 - FR EN mHDgz.mkv" ou les tokens FR/EN/VF/VO/MULTI/VOSTFR
# en fin de chaine ne sont pas precedes d'une annee (donc _AFTER_YEAR_NOISE_RE
# ne match pas). On strip ces tokens (1-3 tokens consecutifs max) y compris
# avec un release group court qui suit.
_TRAILING_LANG_TOKENS_RE = re.compile(
    r"(?:\s+(?:fr|en|vf|vo|vff|vfq|vfi|vof|vostfr|vostr|vost|multi)\b){1,3}\s*$",
    re.IGNORECASE,
)

#: Jetons AMBIGUS en fin de chaine, sans annee pour les ancrer.
#:
#: `_AFTER_YEAR_NOISE_RE` a besoin d'une annee. Sans elle, « Batman - Begins
#: PROPER.mkv » garderait son PROPER. Ce motif prend le relais — mais avec une
#: reserve decisive : `(?<=\S)\s+` exige au moins un caractere AVANT le jeton.
#:
#: Un nom reduit au seul jeton n'est donc PAS touche : « Cam » et « Opus » sont
#: des films (2018, 2025), et les retirer rendait une chaine VIDE. Un tag qui
#: SUIT quelque chose reste un tag ; un jeton qui est TOUT le nom est le titre.
#:
#: LIMITE ASSUMEE : un vrai titre dont le DERNIER mot est l'un de ces sept, et
#: dont le nom de fichier ne porte AUCUNE annee, perd encore ce mot. Le depot
#: avait deja tranche en ce sens (cf. `test_subtitle_preserved_even_with_single
#: _quality_tag`, qui exige « Batman - Begins PROPER » -> « Batman - Begins ») ;
#: on ne fait qu'y decouper le cas « le jeton EST le titre entier ».
_TRAILING_AMBIGU_RE = re.compile(
    r"(?<=\S)\s+(?:proper|internal|limited|complete|hybrid|opus|cam)\b\s*$",
    re.IGNORECASE,
)

# Residus audio : "DTS-HD MA", "DTS-HD HRA", "5.1", "7.1", "2.0", "Atmos".
# NOISE_RE catch "dts-hd" mais pas "ma" / "hra" standalone, et pas les channel counts.
# AUDIT 2026-06-10 (REAL 2/2) : l'ancien pattern `\b(?:ma|hra|[257][\s.]?[01]|
# 2[\s.]?0|atmos)\b` mutilait des TITRES reels : "21 Jump Street" -> "Jump
# Street", "50 First Dates" -> "First Dates", "Ma Vie de Courgette" -> "Vie de
# Courgette", "71 (2014)" -> "2014", "20 000 Leagues" -> "000 Leagues". Causes :
# (a) `[\s.]?` rendait le separateur de canal OPTIONNEL -> "21"/"50"/"71"/"20"
# matchaient comme si c'etait du 2.1/5.0/7.1/2.0 ; (b) "ma"/"hra" nus matchaient
# des mots de titre ("Ma"). On exige desormais un separateur ENTRE le nombre de
# canaux et le ".1/.0" (un vrai tag audio "5.1" devient "5 1" apres le replace
# point->espace), et on retire "ma"/"hra" (trop agressifs ; "DTS-HD MA" est
# deja gere par _NOISE_RE). `[257][\s.][01]` couvre 5.1/7.1/2.1/5.0/7.0/2.0.
# Les canaux (5.1/7.1/2.0) et "atmos" sont insensibles a la casse.
# F33 (2026-07-18) : l'alternative `(?-i:MA|HRA)` a ete RETIREE. Le garde
# title-case ne protegeait que "Ma Vie de Courgette" ; toute release ALL-CAPS
# (courante) etait MUTILEE : "MA.2019.1080p.BluRay.x264-GRP" -> "2019" (query
# TMDb purement numerique = film introuvable), "MA.LOUTE.2016..." -> "LOUTE
# 2016", "MA.VIE.DE.COURGETTE.2016..." -> "VIE DE COURGETTE 2016". Le residu
# "MA"/"HRA" est desormais strippe UNIQUEMENT avec son contexte DTS-HD, via
# _DTS_HD_MASTER_RE ci-dessous. Compromis assume : un "MA" audio sans prefixe
# DTS (ex. "TrueHD.MA.7.1") reste dans le titre — bruit ADDITIF d'un token que
# la similarite TMDb absorbe, la ou l'ancien comportement detruisait le titre.
# Une heuristique qui peut mutiler un titre s'abandonne, elle ne s'itere pas.
# R8-040 (F4) : préfixe DD/DDP optionnel COLLÉ au nombre de canaux. Après
# `name.replace('.',' ')`, "DD5.1" devient "DD5 1" : le `\b` devant `[257]`
# échoue (le 5 est précédé d'une lettre, pas de frontière de mot) -> "DD5 1"/
# "DDP5 1"/"DD7 1" restait et polluait la query TMDb. Le `(?:ddp?)?` optionnel
# absorbe le préfixe sans toucher le strip release-group (R1/R4) ; le séparateur
# OBLIGATOIRE `[\s.]` entre canal et `.1` reste (anti "21 Jump Street"/"50"/"71").
_AUDIO_RESIDUE_RE = re.compile(
    r"\b(?:(?:ddp?)?[257][\s.][01]|atmos)\b",
    re.IGNORECASE,
)

# F33 : residu "MA"/"HRA" strippe UNIQUEMENT avec son contexte DTS-HD (Master
# Audio / High Resolution Audio). Couvre les 3 graphies du corpus reel :
# "DTS-HD.MA", "DTS-HDMA", "DTS HD-MA". DOIT etre applique AVANT _NOISE_RE :
# ce dernier mange "dts"/"dts-hd" et detruirait le contexte.
_DTS_HD_MASTER_RE = re.compile(r"\bdts[\s._-]*hd[\s._-]*(?:ma|hra)\b", re.IGNORECASE)

# F33 : 2e contexte legitime de "MA" = la plateforme source Movies Anywhere,
# qui precede le tag WEB/WEB-DL/WEBRip ("...1080p.MA.WEB-DL.DDP5.1...").
# Verrouille par tests/test_lotd_titles_nfo_tmdbid_v77.py:80 (Avatar 2).
#
# ANCRAGE OBLIGATOIRE SUR LA RESOLUTION (revue adversaire R1). Le lookahead sur
# "web" seul ne suffit PAS a distinguer le tag source d'un titre : il mutilait
# "MA.WEB.2019...", qui rendait "WEB 2019" au lieu de "MA 2019" — exactement la
# classe de defaut que F33 devait supprimer, reintroduite par une autre porte.
# Dans le corpus reel le tag source suit TOUJOURS la resolution
# ("2160p.MA.WEB-DL"), jamais le debut du nom. En exigeant cette resolution, un
# "MA" en tete de titre ne peut plus matcher : la regle devient non ambigue au
# lieu d'etre une heuristique qui peut mutiler un titre.
# La resolution est capturee puis restituee (groupe 1) pour ne pas l'effacer.
# Meme contrainte d'ordre que ci-dessus : AVANT _NOISE_RE, qui mange "web-dl".
_WEB_SOURCE_MA_RE = re.compile(
    r"(\b\d{3,4}p)[\s._-]+(?-i:MA)(?=[\s._-]+web(?:[\s._-]?(?:dl|rip))?\b)",
    re.IGNORECASE,
)

# Year parenthesised : (2010), [2010], {2010}
_PAREN_YEAR_RE = re.compile(r"[\(\[\{]\s*(?:19\d{2}|20\d{2})\s*[\)\]\}]")

# Caracteres de garbage en fin de chaine apres nettoyage
_TRAILING_GARBAGE_RE = re.compile(r"[\s\-_\.]+$")

# Separateurs orphelins en fin de chaine (- ou _ ou . isoles apres strip).
# Utilise dans parse_scene_title pour nettoyer apres release group strip.
_ORPHAN_SEP_RE = re.compile(r"\s+[-_.]+\s*$")

# LOTD-DUP-TITLE-YEAR + BUG-TITLE-CHANNEL-RESIDUE (Lot D 2026-07) : sur un nom
# SANS vraie extension (dossier, release nue), Path.stem traitait le dernier
# segment pointe comme une extension et mangeait ".2005" (l'annee -> identite
# titre+annee divergente selon qu'un tag qualite suit ou non) ou ".1-GRP"
# (canal "7.1" colle au release group -> residu "7" orphelin dans le titre).
# On ne strippe le suffixe que s'il ressemble a une vraie extension de fichier
# (point + lettre + alphanum) : comportement inchange pour ".mkv"/".FRENCH",
# suffixes numeriques/composites (".2005", ".1-GRP", ".0") conserves.
_REAL_FILE_EXT_RE = re.compile(r"^\.[A-Za-z][A-Za-z0-9]*$")

# Release group extraction (Phase Dashboard Podiums).
# Validation d'un candidat (2-25 chars alphanum + underscore, au moins une lettre).
_GROUP_CANDIDATE_RE = re.compile(r"^[A-Za-z0-9_]{2,25}$")

# Marker "scene" qui doit etre present AVANT le dernier tiret pour confirmer
# qu'il s'agit bien d'un release group (et pas d'un tiret interne de titre
# comme "Spider-Man" ou "X-Men").
_SCENE_MARKER_RE = re.compile(
    r"\b(?:19\d{2}|20\d{2}|1080p|2160p|720p|480p|x264|x265|h\.?264|h\.?265|"
    r"hevc|avc|av1|bluray|blu[\s.-]?ray|brrip|bdrip|web[\s.-]?dl|web[\s.-]?rip|"
    r"hdtv|hdrip|dvdrip|remux|truehd|dts|atmos|aac|ac3|10bit|hdr|uhd)\b",
    re.IGNORECASE,
)

# AUDIT 2026-06-11 (R1a) : le garde "vraie release scene" de parse_scene_title
# reutilise directement _NOISE_RE (source unique des tags techniques, defini plus
# bas) AU LIEU d'une liste dupliquee. La 1re version (2026-06-10) avait un
# _TECH_MARKER_RE trop ETROIT (omettait xvid/divx/eac3/ddp/hdlight/amzn...) :
# pour "Old.Movie.1998.XviD-DEiTY" -> "Old Movie 1998 -DEiTY" (release group plus
# strippe -> polluait la query TMDb). _NOISE_RE couvre tous ces tags ET n'inclut
# PAS l'annee (un titre propre comme "Thor - Ragnarok (2017)" reste preserve).

# Source extraction (Phase Dashboard Podiums).
# Detecte la source scene (BluRay, WEB-DL, HDTV, Remux, DVDRip, etc.) dans
# le filename. Retourne le label canonique normalise.
_SOURCE_PATTERNS = [
    # (regex, canonical_label) — ordre important : le plus specifique en premier
    (re.compile(r"\bbd[\s.-]?remux\b", re.IGNORECASE), "BluRay Remux"),
    (re.compile(r"\bremux\b", re.IGNORECASE), "Remux"),
    (re.compile(r"\bblu[\s.-]?ray\b|\bbluray\b", re.IGNORECASE), "BluRay"),
    (re.compile(r"\bbd[\s.-]?rip\b|\bbrrip\b|\bbdrip\b", re.IGNORECASE), "BDRip"),
    (re.compile(r"\bweb[\s.-]?dl\b", re.IGNORECASE), "WEB-DL"),
    (re.compile(r"\bweb[\s.-]?rip\b", re.IGNORECASE), "WEBRip"),
    (re.compile(r"\bhdtv\b", re.IGNORECASE), "HDTV"),
    (re.compile(r"\bhdrip\b", re.IGNORECASE), "HDRip"),
    (re.compile(r"\bdvd[\s.-]?rip\b", re.IGNORECASE), "DVDRip"),
    (re.compile(r"\b(?:cam|camrip|telesync|telecine)\b", re.IGNORECASE), "Cam/TS"),
]


def extract_release_group(filename: str) -> Optional[str]:
    """Extrait le nom du release group depuis un nom de fichier scene.

    Heuristique : le release group est le segment apres le DERNIER tiret du
    stem, validee si le prefixe contient un marker scene (annee, resolution,
    codec). Sans marker scene, le tiret est probablement interne au titre
    ("Spider-Man", "X-Men").

    Examples:
        >>> extract_release_group("Inception.2010.1080p.BluRay.x264-RARBG.mkv")
        'RARBG'
        >>> extract_release_group("Mad.Max.2015.1080p.Atmos-VeXHD.mkv")
        'VeXHD'
        >>> extract_release_group("Spider-Man.2002.1080p.mkv")  # tiret interne
        None
        >>> extract_release_group("Inception.mkv")  # pas de tiret
        None

    Args:
        filename: Nom de fichier brut, avec ou sans extension.

    Returns:
        Nom du groupe (preserve la casse originale, ex: 'VeXHD'), ou None.
    """
    if not filename:
        return None
    # Strip extension d'abord
    p = Path(filename)
    stem = p.stem if p.suffix else p.name
    if not stem:
        return None
    # Cherche le DERNIER tiret du stem
    last_dash = stem.rfind("-")
    if last_dash == -1:
        return None
    prefix = stem[:last_dash]
    candidate = stem[last_dash + 1 :].strip()
    # Valide le format candidat
    if not _GROUP_CANDIDATE_RE.match(candidate):
        return None
    if not any(c.isalpha() for c in candidate):
        return None
    # Heuristique : prefix doit contenir un marker scene (annee/resolution/codec)
    # sinon c'est probablement un tiret interne au titre
    if not _SCENE_MARKER_RE.search(prefix):
        return None
    return candidate


def extract_source(filename: str) -> Optional[str]:
    """Extrait le tag source (BluRay, WEB-DL, HDTV, Remux, etc.) depuis le filename.

    Examples:
        >>> extract_source("Inception.2010.1080p.BluRay.x264-RARBG.mkv")
        'BluRay'
        >>> extract_source("Movie.2024.WEB-DL.x265.mkv")
        'WEB-DL'
        >>> extract_source("Film.2020.BD-Remux.mkv")
        'BluRay Remux'
        >>> extract_source("Random.mkv")
        None

    Args:
        filename: Nom de fichier brut.

    Returns:
        Label canonique de la source, ou None si non detectee.
    """
    if not filename:
        return None
    for pattern, label in _SOURCE_PATTERNS:
        if pattern.search(filename):
            return label
    return None


def _une_passe_de_nettoyage(name: str, *, had_tech_marker: bool, annee_parenthesee: bool) -> str:
    """Une iteration du nettoyage de fin de nom (etapes 6 a 8 du pipeline).

    Extraite de `parse_scene_title` le 2026-08-29 : ajouter le strip des jetons
    ambigus la portait a 118 lignes pour un plafond gele a 117. Le corps de la
    boucle formait deja une unite — « une passe » — et la rendre nommable vaut
    mieux que monter le plafond d'une ligne.

    L'ORDRE compte et n'est pas interchangeable : le release group part avant
    les separateurs orphelins qu'il laisse, l'after-year noise a besoin que ces
    separateurs aient disparu pour matcher, et les jetons ambigus passent en
    DERNIER — quand tout ce qui les precede a ete retire, c'est la seule
    position ou « le jeton EST tout le nom » se distingue de « le jeton SUIT
    quelque chose ».
    """
    # Release group `-GROUP$` — seulement si vraie release (marqueur technique).
    if had_tech_marker:
        name = _RELEASE_GROUP_RE.sub(" ", name)
    # Strip dash/separateurs orphelins en fin (apres release group ou NOISE)
    name = _ORPHAN_SEP_RE.sub("", name)
    name = re.sub(r"\s+", " ", name).strip()
    # Position-aware after-year noise tokens
    name = _AFTER_YEAR_NOISE_RE.sub(r"\1", name)
    name = re.sub(r"\s+", " ", name).strip()
    # Trailing language tokens sans annee prealable
    # (cas "L'arme Fatale 2 - FR EN ...")
    name = _TRAILING_LANG_TOKENS_RE.sub("", name)
    # Jetons ambigus : « Batman - Begins PROPER » perd son tag, « Cam » garde
    # son titre. SAUF si une annee PARENTHESEE a ancre le titre : l'etape 2 a
    # alors garde tout ce qui precedait la parenthese et jete le reste, donc ce
    # qui subsiste est le titre PAR CONSTRUCTION et les tags qui suivaient
    # l'annee sont deja coupes. « Mission Complete (2020) » rendait
    # « Mission » — defaut qui PRE-EXISTAIT a la separation des jetons ambigus
    # (mesure sur origin/main : meme resultat, `_NOISE_RE` retirant `complete`
    # partout).
    if not annee_parenthesee:
        name = _TRAILING_AMBIGU_RE.sub("", name)
    name = _ORPHAN_SEP_RE.sub("", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


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
    # LOTD-DUP-TITLE-YEAR / BUG-TITLE-CHANNEL-RESIDUE : suffixe strippe
    # UNIQUEMENT s'il ressemble a une vraie extension (cf _REAL_FILE_EXT_RE).
    p = Path(filename)
    name = p.stem if (p.suffix and _REAL_FILE_EXT_RE.match(p.suffix)) else p.name
    if name.startswith("."):
        # Cas pathologique ".mkv" / ".mp4" - retour vide
        return ""

    # 1.b Strip provider tags `{tmdb-XXX}` / `[imdbid-ttXXX]` (B02-TAGS-BRACKETS).
    # Doit etre fait AVANT le replace `.` -> ` ` car certains formats peuvent
    # contenir des dots (peu probable mais defensif), et SURTOUT avant le
    # pipeline noise/year/release-group : sinon les chiffres TMDb (ex 27205)
    # peuvent etre confondus avec une annee (annee >= 1900) ou polluer la
    # similarite de titre. Les ids extraits eux-memes sont disponibles via
    # `extract_provider_tags()` pour le futur auto-link deterministe.
    name = strip_provider_tags(name)

    name = name.replace(".", " ").replace("_", " ")

    # AUDIT 2026-06-10/11 (REAL 2/2 + R1a) : on ne strippe un "-GROUP" final QUE si
    # le nom est une vraie release scene (au moins un tag technique present).
    # Calcule AVANT le strip noise (qui retire ces marqueurs). Sinon
    # "Thor - Ragnarok (2017)" -> "Thor". On reutilise _NOISE_RE (source unique
    # des tags : xvid/divx/eac3/ddp/hdlight/x264/web-dl/... ; SANS l'annee, donc
    # un titre propre avec annee reste preserve).
    had_tech_marker = bool(_NOISE_RE.search(name))

    # 2. Position-aware strip si annee parenthesee : strip aussi le suffixe
    # "(year) LANG" → garde uniquement le titre avant la parenthese.
    # Sinon "Le Capitaine Fracasse (1961) FRENCH" -> "Le Capitaine Fracasse FRENCH".
    paren_year_match = _PAREN_YEAR_RE.search(name)
    #: Une annee parenthesee ANCRE le titre : tout ce qui la suit est coupe,
    #: donc ce qui reste ne peut plus porter de tag de release.
    annee_parenthesee = bool(paren_year_match)
    if paren_year_match:
        name = name[: paren_year_match.start()].rstrip(" .-_")

    # 3. Strip noise tags AVANT release group : NOISE_RE retire les tags
    # adjacents au groupe (codec, audio), ce qui isole "-XXXX" en fin de chaine
    # avec un espace avant — matchable par _RELEASE_GROUP_RE.
    # F33 : "DTS-HD MA"/"DTS-HD HRA" et le tag source "MA WEB-DL" se strippent
    # AVANT _NOISE_RE, qui mangerait le "dts"/"web-dl" porteur du contexte et
    # laisserait un "MA" orphelin.
    name = _DTS_HD_MASTER_RE.sub(" ", name)
    # Groupe 1 = la resolution d'ancrage, restituee telle quelle (seul "MA" part).
    name = _WEB_SOURCE_MA_RE.sub(r"\1 ", name)
    name = _NOISE_RE.sub(" ", name)

    # 4. Strip audio residue
    name = _AUDIO_RESIDUE_RE.sub(" ", name)

    # 5. Collapse intermediaire (pour que _RELEASE_GROUP_RE matche " -GROUP" propre)
    name = re.sub(r"\s+", " ", name).strip()

    # 6-7. Loop iteratif : strip release group (-GROUP) + after-year noise + dash
    # orphelins. Necessaire car :
    # - Certains filenames ont des "-XXX" multiples (e.g. Octopussy avec
    #   "-HDMA" residue audio + "-AZAZE" release group).
    # - NOISE_RE peut avoir stripe un release group court (fhd/fw/ms) qu'il
    #   confond avec un tag standard, laissant un dash orphelin "-" qui empeche
    #   l'after-year noise de matcher.
    # Cap a 4 iterations par securite.
    for _ in range(4):
        prev = name
        name = _une_passe_de_nettoyage(name, had_tech_marker=had_tech_marker, annee_parenthesee=annee_parenthesee)
        if name == prev:
            break

    # 8. Final cleanup
    name = _TRAILING_GARBAGE_RE.sub("", name)
    return name.strip(" -_.")
