"""Detection et inventaire des sous-titres externes a cote des videos.

Pas de renommage — les sous-titres suivent le dossier lors du move/rename.
Detection de langue par suffixe de nom de fichier (sous-titres EXTERNES) OU
via les pistes EMBARQUEES dans le conteneur (MKV/MP4) si un probe normalise
est fourni — fix Vague F 2026-05-25 (v1.5.3) : 853 films flagges a tort en
"subtitle_missing_fr" parce que la detection ignorait les pistes embarquees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# -- Extensions sous-titres -------------------------------------------

SUBTITLE_EXTS = frozenset({".srt", ".ass", ".sub", ".sup", ".idx"})

# -- Vocabulaire des langues -------------------------------------------
#
# Une table UNIQUE servait deux vocabulaires incompatibles : les codes ISO des
# pistes EMBARQUEES (ffprobe/MediaInfo, via `_normalize_iso639`) et les tags de
# NOM DE FICHIER (`forced`/`sdh`/`vostfr`..., via `detect_language_from_suffix`).
# Les deux collisions que ce partage produisait :
#
#   * `hi` y etait declare tag « hearing impaired », donc le code ISO 639-1 du
#     HINDI etait efface de toute piste embarquee (et `hin` etait absent de la
#     table) : les pistes hindi disparaissaient de `SubtitleReport.languages`,
#     ce qui levait en prime un faux `subtitle_missing_*`. (#679)
#   * `vo` (« version originale », convention FR de nom de fichier) y etait
#     declare langue ANGLAISE : un `Film.vo.srt` sur un film japonais ou coreen
#     eteignait le signal « sous-titre EN manquant ». (#610)
#
# Les deux vocabulaires sont donc separes. `_ISO639_MAP` ne contient QUE des
# codes de langue reels et est la seule table lue par `_normalize_iso639` ; les
# conventions de nom de fichier vivent dans `_FILENAME_LANG_ALIASES` et
# `_SUBTITLE_FLAG_TOKENS`. Ne JAMAIS reintroduire un tag de nom de fichier dans
# `_ISO639_MAP` : c'est exactement le partage qui a produit ces deux defauts.

_ISO639_MAP: Dict[str, str] = {
    # ISO 639-1
    "fr": "fr",
    "en": "en",
    "es": "es",
    "de": "de",
    "it": "it",
    "pt": "pt",
    "nl": "nl",
    "ja": "ja",
    "zh": "zh",
    "ko": "ko",
    "ru": "ru",
    "ar": "ar",
    "pl": "pl",
    "sv": "sv",
    "da": "da",
    "fi": "fi",
    "no": "no",
    "cs": "cs",
    "hu": "hu",
    "ro": "ro",
    "tr": "tr",
    "el": "el",
    "he": "he",
    "hi": "hi",  # HINDI (#679) — le tag « hearing impaired » est `sdh`, pas `hi`
    "th": "th",
    "vi": "vi",
    # ISO 639-2 / bibliographic
    "fre": "fr",
    "fra": "fr",
    "eng": "en",
    "spa": "es",
    "ger": "de",
    "deu": "de",
    "ita": "it",
    "por": "pt",
    "dut": "nl",
    "nld": "nl",
    "jpn": "ja",
    "chi": "zh",
    "zho": "zh",
    "kor": "ko",
    "rus": "ru",
    "ara": "ar",
    "pol": "pl",
    "swe": "sv",
    "dan": "da",
    "fin": "fi",
    "nor": "no",
    "cze": "cs",
    "ces": "cs",
    "hun": "hu",
    "rum": "ro",
    "ron": "ro",
    "tur": "tr",
    "gre": "el",
    "ell": "el",
    "heb": "he",
    "hin": "hi",  # #679 : absent de la table, donc hindi non resolvable
    "tha": "th",
    "vie": "vi",
    # Noms courants
    "french": "fr",
    "english": "en",
    "spanish": "es",
    "german": "de",
    "italian": "it",
    "portuguese": "pt",
    "dutch": "nl",
    "japanese": "ja",
    "chinese": "zh",
    "korean": "ko",
    "russian": "ru",
    "arabic": "ar",
    "polish": "pl",
    "swedish": "sv",
    "danish": "da",
    "finnish": "fi",
    "norwegian": "no",
    "czech": "cs",
    "hungarian": "hu",
    "romanian": "ro",
    "turkish": "tr",
    "greek": "el",
    "hebrew": "he",
    "hindi": "hi",
    "thai": "th",
    "vietnamese": "vi",
    # Codes ISO 639-2 qui existent mais ne designent aucune langue identifiable.
    "und": "",
}

# Conventions de NOM DE FICHIER qui portent malgre tout une langue. Elles ne
# sont PAS des codes ISO : ffprobe ne les emet jamais, et `_normalize_iso639`
# ne doit donc pas les connaitre.
_FILENAME_LANG_ALIASES: Dict[str, str] = {
    "vostfr": "fr",  # VO sous-titree francais : le SOUS-TITRE, lui, est francais
    "vf": "fr",
}

# Tokens de nom de fichier qui ne designent AUCUNE langue. `vo` en fait partie
# (#610) : « version originale » ne dit rien de la langue — l'assimiler a
# l'anglais inventait une langue sur tout film non anglophone et eteignait le
# signal `subtitle_missing_en`. `multi` non plus : il annonce une pluralite,
# jamais une langue precise.
_NON_LANGUAGE_TOKENS = frozenset({"forced", "sdh", "cc", "commentary", "multi", "und", "vo", "default", "foreign"})

# Table de lecture des SUFFIXES de nom de fichier = codes ISO + alias FR.
_FILENAME_LANG_MAP: Dict[str, str] = {**_ISO639_MAP, **_FILENAME_LANG_ALIASES}


def _lang_from_filename_token(token: str) -> str:
    """Langue ISO 639-1 portee par un token de nom de fichier, "" sinon."""
    if token in _NON_LANGUAGE_TOKENS:
        return ""
    return _FILENAME_LANG_MAP.get(token, "")


def _normalize_expected_language(raw: str) -> str:
    """Normalise une langue ATTENDUE **saisie par l'utilisateur** vers ISO 639-1.

    Jumelle de `_normalize_iso639`, deliberement DISTINCTE d'elle : les deux
    normalisent une langue, mais pas la meme population d'entrees.

      * `_normalize_iso639` lit ce que produit un DEMUXEUR (ffprobe/MediaInfo).
        `vf`/`vostfr` n'y existent pas — les y remettre est exactement le
        partage de table qui a efface le hindi (#679) et fabrique un faux
        anglais (#610).
      * ici l'entree est du TEXTE LIBRE tape dans « Langues attendues »
        (`settings_support._normalize_lang_list` n'applique aucune liste
        blanche), sur une application francophone : `vf` et `vostfr` sont des
        saisies parfaitement normales, et le vocabulaire a lire est donc celui
        des conventions de nom de fichier.

    Regression que cette fonction evite (revue adverse PR #856) : brancher la
    saisie utilisateur sur `_ISO639_MAP` rendait `vf`/`vostfr` non resolvables,
    donc jamais egaux au `fr` reellement detecte -> `subtitle_missing_vf` sur
    100 % de la bibliotheque. Et cela A LA LECTURE (`generate_suggestions`
    normalise les attendues a chaque appel), donc sans re-scan : l'ecran vire
    au rouge tout seul au redemarrage.
    """
    return _lang_from_filename_token((raw or "").strip().lower())


# F12 (revue post-merge 2026-07-18) — tags de VARIANTE places APRES le code
# langue par les conventions Plex (`.fr.forced`, `.en.sdh`) et Jellyfin
# (`.fr.default`, `.en.forced`, `.fr.cc`). Ces tokens ne sont PAS des langues :
# la detection les traverse pour trouver le code langue reel juste avant. Tout
# token INCONNU (donc potentiellement un morceau de titre) arrete la marche
# arriere — c'est cette borne qui interdit de lire un mot du titre comme une
# langue, elle ne doit jamais etre relachee en "scanner tous les tokens".
_SUBTITLE_FLAG_TOKENS = frozenset({"forced", "sdh", "cc", "hi", "default", "foreign", "commentary"})

# `hi` est le seul token a la fois code ISO (hindi) et tag de variante
# (« hearing impaired » chez Jellyfin) — cf. `_classify_subtitle_suffix`.
# Nomme `_HI_CODE` et pas `_HI_TOKEN` : un nom finissant par `_TOKEN` declenche
# S105/bandit B105 (« hardcoded password ») chez Codacy, qui faisait echouer un
# check sur un faux positif. `_CODE` est de toute facon plus juste — c'est le
# code ISO 639-1, pas un token de nom de fichier.
_HI_CODE = "hi"


def _subtitle_suffix_tokens(filename: str, video_stem: Optional[str] = None) -> Tuple[List[str], bool]:
    """Tokens du nom de sous-titre situes APRES le nom de la video.

    Retourne `(tokens, bornes)`. `bornes` vaut True uniquement quand le stem de
    la video a reellement prefixe le nom : c'est la SEULE situation ou l'on sait
    que tout ce qui reste est un tag, et donc la seule ou l'on s'autorise a
    traverser un tag de variante pour lire la langue derriere.

    F12 / revue adverse : la borne « premier token inconnu = stop » ne suffit
    PAS quand le dernier mot du titre est lui-meme une cle de `_LANG_MAP`. La
    marche arriere traversait le tag de variante puis lisait ce mot :
    'Dr.No.forced.srt' rendait 'no' (norvegien) sur le film « Dr. No », et
    'Movie.Chapter.It.forced.srt' rendait 'it'. Une langue INVENTEE remonte
    ensuite telle quelle en Bibliotheque et au dashboard.

    Quand l'appelant connait le stem de la video (chemin nominal :
    `match_subtitles_to_video` / `build_subtitle_report`), la borne devient
    EXACTE — seuls les tokens ajoutes apres le nom de la video peuvent etre des
    tags. Sinon (sous-titre orphelin, appel direct) on retombe sur la borne
    historique « ne jamais lire le premier token » (= le titre), strictement
    inchangee.

    Cas `sub_stem == video_stem` (aucun token ajoute) : on garde deliberement la
    borne historique. 'Film.VOSTFR.srt' a cote de 'Film.VOSTFR.mkv' doit
    continuer a rendre 'fr' — c'est le comportement d'avant F12, le corriger
    ferait apparaitre de faux `subtitle_missing_fr`.
    """
    stem = Path(filename).stem
    if video_stem:
        prefix = video_stem.lower() + "."
        if stem.lower().startswith(prefix):
            return stem[len(prefix) :].split("."), True
    parts = stem.split(".")
    if len(parts) < 2:
        return [], False
    return parts[1:], False


def _classify_subtitle_suffix(filename: str, video_stem: Optional[str] = None) -> Tuple[str, Set[str]]:
    """Lit UNE fois le suffixe d'un sous-titre : `(langue, tags de variante)`.

    Point d'entree unique de `detect_language_from_suffix` et de
    `_subtitle_flag_tokens`. Les deux parcouraient les memes tokens avec deux
    logiques d'arret ecrites separement : rien ne garantissait qu'elles restent
    d'accord sur le role d'un token, et c'est precisement ce desaccord qui a
    permis a `hi` d'etre une langue pour l'une et un tag pour l'autre.

    Arbitrage `hi` (#679) : `hi` est a la fois le code ISO 639-1 du HINDI et
    l'abreviation Jellyfin de « hearing impaired ». La convention du projet est
    d'ecrire `sdh` pour le malentendant, donc :

      * `hi` precede d'un autre code langue est une VARIANTE de cette langue —
        'Film.en.hi.srt' -> ('en', {'hi'}) ;
      * `hi` SEUL est la langue hindi — 'Film.hi.srt' -> ('hi', set()).

    Corollaire indispensable : le token qui PORTE la langue ne peut pas etre en
    meme temps un tag de variante, sinon un sous-titre hindi serait exclu du
    decompte des doublons comme s'il etait une piste malentendant.
    """
    tokens, bounded = _subtitle_suffix_tokens(filename, video_stem)
    if not tokens:
        return "", set()

    # 1. Tags de variante : uniquement les tokens CONNUS et CONTIGUS en fin de
    #    nom (borne F12). Un mot de titre homonyme d'un tag
    #    ('The.Foreign.Exchange.fr.srt') ne doit pas faire sauter le sous-titre
    #    du comptage `lang_counts`, donc perdre un VRAI doublon de langue.
    tags: Set[str] = set()
    for raw in reversed(tokens):
        token = raw.strip().lower()
        if not token:
            continue
        if token not in _SUBTITLE_FLAG_TOKENS:
            break
        tags.add(token)

    # 2. Langue. Sans le stem de la video la borne est inexacte : on ne traverse
    #    RIEN et on lit le dernier token seul (semantique d'avant F12).
    language = ""
    hi_is_the_language = False
    if not bounded:
        last = tokens[-1].strip().lower()
        language = _lang_from_filename_token(last)
        hi_is_the_language = last == _HI_CODE and bool(language)
    else:
        for raw in reversed(tokens):
            token = raw.strip().lower()
            if not token:
                continue
            if token == _HI_CODE:
                # Ambigu : arbitre apres la marche arriere, quand on sait si un
                # autre code langue le precedait.
                continue
            lang = _lang_from_filename_token(token)
            if lang:
                language = lang
                break
            if token in _SUBTITLE_FLAG_TOKENS or token in _NON_LANGUAGE_TOKENS:
                # Tokens CONNUS pour ne porter aucune langue : on les traverse.
                # `_NON_LANGUAGE_TOKENS` ajoute ici `vo`/`multi`/`und`, qui ne
                # sont pas des tags de variante (ils restent donc hors de
                # `tags`) mais arretaient quand meme la marche arriere :
                # 'Film.fr.vo.srt' rendait '' alors que le sous-titre est
                # explicitement 'fr'. Traverser est sans risque ici — on est
                # dans la branche BORNEE, ou tout token vient APRES le nom de
                # la video et ne peut donc pas etre un mot du titre.
                continue
            # Token inconnu (mot du titre, resolution, groupe...) : on s'arrete.
            break
        if not language and _HI_CODE in tags:
            language = _ISO639_MAP[_HI_CODE]
            hi_is_the_language = True

    if hi_is_the_language:
        tags.discard(_HI_CODE)
    return language, tags


def _subtitle_flag_tokens(filename: str, *, video_stem: Optional[str] = None) -> Set[str]:
    """Tags de variante (forced/sdh/cc/...) portes par un nom de sous-titre.

    Revue adverse F12 : cette fonction balayait TOUS les tokens de suffixe alors
    que sa docstring promettait le comportement de `detect_language_from_suffix`.
    Un mot de titre homonyme d'un tag ('The.Foreign.Exchange.fr.srt' ->
    {'foreign'}) faisait sauter le sous-titre du comptage `lang_counts`, donc
    perdre un VRAI doublon de langue. On ne collecte donc que les tags
    CONTIGUS en fin de nom, avec la meme borne d'arret.
    """
    return _classify_subtitle_suffix(filename, video_stem)[1]


# -- Dataclasses -------------------------------------------------------


@dataclass(frozen=True)
class SubtitleInfo:
    """Info sur un fichier sous-titre detecte."""

    filename: str
    ext: str
    language: str  # ISO 639-1 ("fr", "en") ou "" si inconnu
    language_source: str  # "suffix" | "unknown"
    is_orphan: bool  # True si pas de video correspondante


@dataclass(frozen=True)
class SubtitleReport:
    """Resume des sous-titres pour un film (une video dans un dossier)."""

    count: int
    languages: List[str]  # langues uniques detectees
    formats: List[str]  # extensions uniques
    orphans: int  # sous-titres sans video associee
    missing_languages: List[str]  # langues attendues absentes
    duplicate_languages: List[str]  # langues detectees en double
    details: List[SubtitleInfo]  # liste complete
    # ARBITRAGE F12 tranche le 2026-08-03 (cf. build_subtitle_report) : langues
    # ATTENDUES presentes UNIQUEMENT sous forme de piste FORCEE (dialogues en
    # langue etrangere) — donc sans piste complete. Disjoint de
    # `missing_languages` par construction : une langue forced-only EST detectee.
    # Champ ajoute EN DERNIER avec un defaut : `SubtitleReport(0, [], [], 0, [], [], [])`
    # (construction positionnelle a 7 arguments) reste valide.
    forced_only_languages: List[str] = field(default_factory=list)


# -- Paires VobSub -----------------------------------------------------

_VOBSUB_INDEX_EXT = ".idx"
_VOBSUB_DATA_EXT = ".sub"


def _vobsub_index_companions(subtitles: List[SubtitleInfo]) -> Set[str]:
    """Noms des `.idx` qui ne sont que l'INDEX d'un `.sub` VobSub voisin.

    Un sous-titre VobSub (DVD, remux) est TOUJOURS une paire `<nom>.idx`
    (index temporel) + `<nom>.sub` (bitmaps) : deux fichiers pour UN seul
    sous-titre. Le decompte des doublons les comptait comme deux pistes de la
    meme langue et levait `subtitle_duplicate_lang` sur toute bibliotheque de
    DVD remuxes (#749).

    Le correctif F12 des tags de variante ne couvre PAS ce cas : la paire ne
    porte aucun tag (`Film.fr.idx` / `Film.fr.sub`), donc rien ne l'excluait —
    verifie sur main avant correctif. Un `.idx` SANS `.sub` frere reste compte :
    il est alors le seul fichier qui represente ce sous-titre.

    L'appartenance a une paire se verifie par la PRESENCE du `.sub` frere, jamais
    par la seule extension `.idx` : ecarter tout `.idx` masquerait un VRAI
    doublon (`Film.fr.idx` orphelin a cote de `Film.fr.srt`), donc ferait taire
    une alerte — le mauvais sens. Aucune autre couche ne materialise la paire :
    `domain.core.classify_sidecars` rattache les sidecars UN PAR UN par leur
    stem, et `SIDECAR_METADATA_EXTS` / `RESIDUAL_SUBTITLE_EXTS` listent `.idx` et
    `.sub` comme deux entrees independantes. Le seul endroit ou les deux
    fichiers doivent redevenir UN, c'est ce decompte-ci.
    """
    data_stems = {Path(s.filename).stem.lower() for s in subtitles if s.ext == _VOBSUB_DATA_EXT}
    return {s.filename for s in subtitles if s.ext == _VOBSUB_INDEX_EXT and Path(s.filename).stem.lower() in data_stems}


# -- Fonctions publiques -----------------------------------------------


def detect_language_from_suffix(filename: str, *, video_stem: Optional[str] = None) -> str:
    """Detecte la langue depuis le suffixe du nom de fichier.

    Ex: 'Inception.fr.srt' → 'fr', 'Movie.eng.srt' → 'en', 'Movie.srt' → ''

    F12 (revue post-merge 2026-07-18) : la version precedente ne lisait que le
    DERNIER token (`rsplit('.', 1)`), donc les conventions Plex/Jellyfin
    `Film.fr.forced.srt` / `Film.en.sdh.srt` rendaient '' -> faux flag
    `subtitle_missing_fr` sur un film qui A son sous-titre FR. On remonte
    maintenant les tokens de droite a gauche en traversant UNIQUEMENT les tags
    de variante connus (_SUBTITLE_FLAG_TOKENS) et on s'arrete au premier token
    inconnu. Le premier token (le titre) n'est JAMAIS lu : 'The.Danish.Girl.srt'
    ou 'French.Connection.1971.srt' rendent toujours ''.

    `video_stem` (revue adverse) borne la marche arriere au nom de la video :
    sans lui, traverser un tag de variante pouvait faire lire le DERNIER MOT DU
    TITRE comme une langue ('Dr.No.forced.srt' -> 'no' sur le film « Dr. No »).
    Aucune heuristique ne distingue 'Dr.No.forced' de 'Inception.fr.forced' sans
    connaitre la video : hors de ce contexte on NE TRAVERSE DONC PAS, on rend
    exactement ce que rendait la version d'avant F12 (dernier token seul). Le
    chemin de production (`build_subtitle_report` -> `match_subtitles_to_video`)
    fournit toujours `video_stem` et beneficie, lui, du support Plex/Jellyfin.

    `hi` : 'Film.hi.srt' rend 'hi' (HINDI) et 'Film.en.hi.srt' rend 'en' — voir
    l'arbitrage complet dans `_classify_subtitle_suffix`. `vo` ne rend plus 'en'
    (#610) : « version originale » n'est pas une langue.

    LIMITE connue, SANS `video_stem` : le dernier token etant lu seul,
    'Film.en.hi.srt' rend 'hi' (hindi) la ou le mode borne rend 'en'. C'est le
    prix de la borne historique — sans le nom de la video, rien ne dit que `en`
    est un tag de langue et pas le dernier mot du titre. Le chemin de
    production (`build_subtitle_report` -> `match_subtitles_to_video`) fournit
    toujours `video_stem` ; passer ce parametre est donc recommande.
    """
    return _classify_subtitle_suffix(filename, video_stem)[0]


def find_subtitles_in_folder(folder: Path) -> List[SubtitleInfo]:
    """Liste tous les fichiers sous-titres dans un dossier (non recursif)."""
    results: List[SubtitleInfo] = []
    try:
        entries = list(folder.iterdir())
    except (PermissionError, OSError):
        return []

    for entry in entries:
        if not entry.is_file():
            continue
        ext = entry.suffix.lower()
        if ext not in SUBTITLE_EXTS:
            continue
        lang = detect_language_from_suffix(entry.name)
        lang_source = "suffix" if lang else "unknown"
        results.append(
            SubtitleInfo(
                filename=entry.name,
                ext=ext,
                language=lang,
                language_source=lang_source,
                is_orphan=True,  # sera corrige par match_subtitles_to_video
            )
        )
    return sorted(results, key=lambda s: s.filename.lower())


def match_subtitles_to_video(
    subtitles: List[SubtitleInfo],
    video_stem: str,
) -> List[SubtitleInfo]:
    """Filtre les sous-titres qui correspondent a une video (par stem).

    Match si : sub_stem == video_stem OU sub_name commence par video_stem + '.'
    Les sous-titres matches sont retournes avec is_orphan=False.
    """
    if not video_stem:
        return []
    vs = video_stem.lower()
    matched: List[SubtitleInfo] = []
    for sub in subtitles:
        sub_name_no_ext = Path(sub.filename).stem.lower()
        # Exact stem match (ex: Movie.srt ↔ Movie.mkv)
        # Ou prefix match (ex: Movie.fr.srt ↔ Movie.mkv)
        if sub_name_no_ext == vs or sub_name_no_ext.startswith(vs + "."):
            # Revue adverse F12 : `find_subtitles_in_folder` a devine la langue
            # SANS connaitre la video. Ici on la connait : on re-derive avec la
            # borne exacte, seul endroit ou la mutilation 'Dr.No.forced.srt' ->
            # 'no' peut etre coupee. Pour un match de stem EXACT, la re-derivation
            # retombe sur la borne historique et rend la meme valeur.
            lang = detect_language_from_suffix(sub.filename, video_stem=video_stem)
            matched.append(
                SubtitleInfo(
                    filename=sub.filename,
                    ext=sub.ext,
                    language=lang,
                    language_source="suffix" if lang else "unknown",
                    is_orphan=False,
                )
            )
    return matched


def _normalize_iso639(raw: str) -> str:
    """Normalise un tag de langue ISO 639-1/-2/-3 vers ISO 639-1.

    Vague F 2026-05-25 (v1.5.3) : aligne la detection des pistes embarquees
    (ex: ffprobe expose `fra`, `fre`, MediaInfo `fr`). Renvoie "" si non
    resolvable ou si le code ne designe aucune langue (`und`).

    Lit `_ISO639_MAP` et RIEN d'autre : les tags de nom de fichier
    (`forced`/`sdh`/`vostfr`/`vo`) n'ont aucun sens pour une piste embarquee et
    les melanger a cette table est ce qui a efface le hindi (#679) et fabrique
    un faux anglais (#610).
    """
    return _ISO639_MAP.get((raw or "").strip().lower(), "")


# Une paire VobSub, c'est DEUX fichiers de meme stem : `.sub` porte le flux
# bitmap, `.idx` l'index des timings/offsets. L'un sans l'autre est illisible.
_VOBSUB_DATA_EXT = ".sub"
_VOBSUB_INDEX_EXT = ".idx"


def build_subtitle_report(
    folder: Path,
    video: Path,
    expected_languages: Optional[List[str]] = None,
    *,
    embedded_subtitles: Optional[List[Dict[str, Any]]] = None,
) -> SubtitleReport:
    """Construit le rapport sous-titres pour une video dans un dossier.

    1. Trouve tous les sous-titres EXTERNES (fichiers .srt/.ass/.sub a cote)
    2. Matche ceux qui correspondent a la video (par stem)
    3. Detecte les langues EXTERNES (suffixe) + EMBARQUEES (probe ffprobe/mediainfo)
    4. Verifie les langues attendues vs union(externes, embarquees)
    5. Detecte les orphelins (externes) et doublons (externes)
    6. Detecte les langues attendues couvertes SEULEMENT par une piste FORCEE
       (`forced_only_languages`, arbitrage F12 tranche le 2026-08-03 — voir le
       commentaire detaille au-dessus du calcul des langues externes)

    Fix Vague F 2026-05-25 (v1.5.3) : `embedded_subtitles` (optionnel, default
    None pour backward-compat) est la liste `normalized_probe["subtitles"]`,
    chaque item est `{"index": int, "language": str|None, "forced": bool}`.
    Les langues embarquees fusionnent avec les externes pour le calcul des
    langues manquantes — fixant les 853 films flagges a tort.
    """
    all_subs = find_subtitles_in_folder(folder)
    video_stem = video.stem
    matched = match_subtitles_to_video(all_subs, video_stem)

    # Orphelins : sous-titres du dossier qui ne matchent aucune video
    matched_filenames = {s.filename.lower() for s in matched}
    orphan_count = sum(1 for s in all_subs if s.filename.lower() not in matched_filenames)

    # Langues externes (fichiers .srt/.ass/... a cote du .mkv)
    #
    # ARBITRAGE PRODUIT TRANCHE le 2026-08-03 (revue adverse F12) : un sous-titre
    # FORCE ne traduit que les passages en langue etrangere — ce n'est PAS une
    # piste complete. Un dossier qui ne contient QUE 'Film.fr.forced.srt' ne doit
    # donc plus laisser croire que le FR est couvert.
    #
    # Option ECARTEE — « compter un .forced comme absent » (le pousser dans
    # `missing_languages`) : elle serait INOPERANTE. Le fichier EST un sous-titre
    # 'fr', donc 'fr' reste dans `languages`, et TOUS les consommateurs aval
    # jettent le signal « manquant » des que la langue figure parmi les langues
    # presentes — le FLAG (ui.api.run_read_support.reconcile_subtitle_flags,
    # domain.duplicate_support._reconciled_row_flags, ui.api.dashboard_support
    # ._build_row_payload) comme la LISTE (meme _build_row_payload,
    # ui.api.library_support._build_library_rows:395). L'alerte serait posee au
    # scan puis effacee avant d'atteindre le moindre ecran. La rendre visible
    # imposerait de retirer AUSSI 'fr' de
    # `languages`, c.-a-d. d'affirmer que le dossier n'a aucun sous-titre FR alors
    # qu'il en a un : perte d'information seche (affichage Bibliotheque, compteurs
    # « sans subs FR », doublons de langue).
    #
    # Option RETENUE — signal ORTHOGONAL `forced_only_languages` -> flag
    # `subtitle_forced_only_<lang>` : `languages` et `missing_languages` restent
    # exacts, et le nouveau prefixe traverse intact les reconciliations ci-dessus,
    # qui ne connaissent que `subtitle_missing_`.
    external_languages: Set[str] = set()
    external_full_languages: Set[str] = set()  # langues avec une piste NON forcee
    for sub in matched:
        if not sub.language:
            continue
        external_languages.add(sub.language)
        if "forced" not in _subtitle_flag_tokens(sub.filename, video_stem=video_stem):
            external_full_languages.add(sub.language)

    # Langues embarquees (pistes subtitle dans le conteneur)
    # Fix audit 2026-05-25 (v1.5.3) Vague F : auparavant ignorees → faux
    # positifs "subtitle_missing_fr" sur 853 films avec FR embarque.
    embedded_languages: Set[str] = set()
    embedded_full_languages: Set[str] = set()
    if embedded_subtitles:
        for track in embedded_subtitles:
            if not isinstance(track, dict):
                continue
            raw_lang = (track.get("language") or "").strip().lower()
            if not raw_lang:
                # piste sans tag de langue → ignoree (ne pas inventer)
                continue
            normalized = _normalize_iso639(raw_lang)
            if normalized:
                embedded_languages.add(normalized)
                # `forced` est expose par les deux normaliseurs de probe
                # (_normalize_ffprobe : tag OU disposition ; _normalize_mediainfo).
                # Absent/None → piste consideree COMPLETE (on n'invente pas un
                # defaut a partir d'une info manquante).
                if not track.get("forced"):
                    embedded_full_languages.add(normalized)

    all_languages = external_languages | embedded_languages
    full_languages = external_full_languages | embedded_full_languages

    languages = sorted(all_languages)
    formats = sorted({s.ext for s in matched})

    # Fix audit 2026-05-26 (v1.5.6) Vague L (subs-3) : normalisation SYMETRIQUE.
    # Avant, `expected_languages` etait seulement .lower().strip() sans passer par
    # _LANG_MAP. Donc une attente saisie en ISO 639-2 ou en nom courant
    # ('french'/'francais'/'fra'/'fre') ne matchait JAMAIS les langues detectees
    # (deja normalisees en 'fr') -> tous les films flagges "manquant" a tort.
    # Maintenant : on normalise les DEUX cotes, et on compare des codes ISO
    # 639-1 canoniques. On garde le code original dans la liste `missing` quand
    # il n'est pas resolvable (pour ne pas masquer une saisie utilisateur
    # erronee).
    #
    # Le normaliseur est `_normalize_expected_language`, PAS `_normalize_iso639` :
    # ce cote-ci de la comparaison est de la SAISIE UTILISATEUR (texte libre,
    # sans liste blanche), pas une sortie de demuxeur. Un francophone qui tape
    # `vf` ou `vostfr` doit continuer a matcher son `fr` detecte.
    expected_pairs = [
        (raw, _normalize_expected_language(raw))
        for raw in (lang.strip() for lang in (expected_languages or []) if lang)
        if raw
    ]
    missing = [(norm or raw) for raw, norm in expected_pairs if (norm or raw.lower()) not in all_languages]

    # Langues ATTENDUES detectees mais SANS piste complete (que du .forced).
    # Restreint aux langues attendues, comme `missing` : un '.en.forced.srt' sur
    # un film ou l'EN n'est pas attendu n'interesse pas l'utilisateur.
    expected_keys = {(norm or raw.lower()) for raw, norm in expected_pairs}
    forced_only = sorted((expected_keys & all_languages) - full_languages)

    # Doublons de langue : restent sur les sous-titres EXTERNES uniquement
    # (un MKV avec 2 pistes FR embarquees n'est pas un probleme utilisateur).
    #
    # DEUX exclusions INDEPENDANTES se cumulent ici. Elles ne se recouvrent pas :
    # un cas exclu par l'une n'est jamais vu par l'autre.
    #
    # (1) F12 corollaire OBLIGATOIRE : depuis que `.fr.forced.srt` resout bien
    #     'fr', la paire LEGITIME `Film.fr.srt` + `Film.fr.forced.srt` (piste
    #     complete + piste forcee, convention Plex/Jellyfin) compterait 2 fois
    #     'fr' et leverait `subtitle_duplicate_lang` a tort. On ne compte donc
    #     que les sous-titres SANS tag de variante.
    #
    # (2) #749 : une paire VobSub (`Film.fr.idx` + `Film.fr.sub`, meme stem) est
    #     UN seul sous-titre stocke en deux fichiers. Elle ne porte AUCUN tag de
    #     variante, donc l'exclusion (1) ne la voit pas et 'fr' etait compte 2
    #     fois. L'index reste dans `count`, `formats` et `languages` — ce sont
    #     des mesures de FICHIERS ; seul le decompte des doublons l'ecarte.
    vobsub_index_files = _vobsub_index_companions(matched)
    lang_counts: Dict[str, int] = {}
    for s in matched:
        if not s.language:
            continue
        if s.filename in vobsub_index_files:
            continue
        if _subtitle_flag_tokens(s.filename, video_stem=video_stem):
            continue
        lang_counts[s.language] = lang_counts.get(s.language, 0) + 1
    duplicates = sorted(lang for lang, cnt in lang_counts.items() if cnt > 1)

    return SubtitleReport(
        count=len(matched),
        languages=languages,
        formats=formats,
        orphans=orphan_count,
        missing_languages=missing,
        duplicate_languages=duplicates,
        details=matched,
        forced_only_languages=forced_only,
    )
