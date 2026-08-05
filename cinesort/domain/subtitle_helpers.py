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

# -- Mapping langues (ISO 639-1 ← ISO 639-2, noms courants, tags) ----

_LANG_MAP: Dict[str, str] = {
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
    "thai": "th",
    "vietnamese": "vi",
    # Tags speciaux (pas des langues → "")
    "forced": "",
    "sdh": "",
    "hi": "",
    "cc": "",
    "commentary": "",
    "multi": "",
    "und": "",
    # Tags FR courants
    "vostfr": "fr",
    "vf": "fr",
    "vo": "en",
}

# F12 (revue post-merge 2026-07-18) — tags de VARIANTE places APRES le code
# langue par les conventions Plex (`.fr.forced`, `.en.sdh`) et Jellyfin
# (`.fr.default`, `.en.forced`, `.fr.cc`). Ces tokens ne sont PAS des langues :
# la detection les traverse pour trouver le code langue reel juste avant. Tout
# token INCONNU (donc potentiellement un morceau de titre) arrete la marche
# arriere — c'est cette borne qui interdit de lire un mot du titre comme une
# langue, elle ne doit jamais etre relachee en "scanner tous les tokens".
_SUBTITLE_FLAG_TOKENS = frozenset({"forced", "sdh", "cc", "hi", "default", "foreign", "commentary"})


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


def _subtitle_flag_tokens(filename: str, *, video_stem: Optional[str] = None) -> Set[str]:
    """Tags de variante (forced/sdh/cc/...) portes par un nom de sous-titre.

    Revue adverse F12 : cette fonction balayait TOUS les tokens de suffixe alors
    que sa docstring promettait le comportement de `detect_language_from_suffix`.
    Un mot de titre homonyme d'un tag ('The.Foreign.Exchange.fr.srt' ->
    {'foreign'}) faisait sauter le sous-titre du comptage `lang_counts`, donc
    perdre un VRAI doublon de langue. On ne collecte donc que les tags
    CONTIGUS en fin de nom, avec la meme borne d'arret.
    """
    tokens, _bounded = _subtitle_suffix_tokens(filename, video_stem)
    found: Set[str] = set()
    for raw in reversed(tokens):
        token = raw.strip().lower()
        if not token:
            continue
        if token not in _SUBTITLE_FLAG_TOKENS:
            break
        found.add(token)
    return found


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
    """
    tokens, bounded = _subtitle_suffix_tokens(filename, video_stem)
    if not tokens:
        return ""
    if not bounded:
        return _LANG_MAP.get(tokens[-1].strip().lower(), "")
    for raw in reversed(tokens):
        token = raw.strip().lower()
        if not token:
            continue
        lang = _LANG_MAP.get(token, "")
        if lang:
            return lang
        if token in _SUBTITLE_FLAG_TOKENS:
            continue
        # Token inconnu (mot du titre, resolution, groupe...) : on s'arrete.
        return ""
    return ""


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

    Vague F 2026-05-25 (v1.5.3) : utilise _LANG_MAP pour aligner la detection
    des pistes embarquees (ex: ffprobe expose `fra`, `fre`, MediaInfo `fr`).
    Renvoie "" si non resolvable ou tag special (forced/sdh/...).
    """
    return _LANG_MAP.get((raw or "").strip().lower(), "")


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
    # Maintenant : on normalise les DEUX cotes via _normalize_iso639, et on
    # compare des codes ISO 639-1 canoniques. On garde le code original dans la
    # liste `missing` quand il n'est pas resolvable (pour ne pas masquer une
    # saisie utilisateur erronee).
    expected_pairs = [
        (raw, _normalize_iso639(raw)) for raw in (lang.strip() for lang in (expected_languages or []) if lang) if raw
    ]
    missing = [(norm or raw) for raw, norm in expected_pairs if (norm or raw.lower()) not in all_languages]

    # Langues ATTENDUES detectees mais SANS piste complete (que du .forced).
    # Restreint aux langues attendues, comme `missing` : un '.en.forced.srt' sur
    # un film ou l'EN n'est pas attendu n'interesse pas l'utilisateur.
    expected_keys = {(norm or raw.lower()) for raw, norm in expected_pairs}
    forced_only = sorted((expected_keys & all_languages) - full_languages)

    # Doublons de langue : restent sur les sous-titres EXTERNES uniquement
    # (un MKV avec 2 pistes FR embarquees n'est pas un probleme utilisateur).
    # F12 corollaire OBLIGATOIRE : depuis que `.fr.forced.srt` resout bien 'fr',
    # la paire LEGITIME `Film.fr.srt` + `Film.fr.forced.srt` (piste complete +
    # piste forcee, convention Plex/Jellyfin) compterait 2 fois 'fr' et leverait
    # `subtitle_duplicate_lang` a tort. On ne compte donc que les sous-titres
    # SANS tag de variante : deux `.fr.srt` restent impossibles (meme nom), deux
    # variantes taguees ne sont pas un doublon utilisateur.
    lang_counts: Dict[str, int] = {}
    for s in matched:
        if not s.language:
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
