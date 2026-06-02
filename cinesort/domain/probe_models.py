from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Dict, List, Optional

PROBE_QUALITY_FULL = "FULL"
PROBE_QUALITY_PARTIAL = "PARTIAL"
PROBE_QUALITY_FAILED = "FAILED"


# BUG-018 (hotfix1, 2026-06-02) : helpers centralises de comparaison
# probe_quality. Le pipeline interne (_normalize_merge) produit toujours
# UPPERCASE via la constante PROBE_QUALITY_FAILED, mais l'audit a montre
# que certains consommateurs UI comparent en case-sensitive (== "FAILED")
# alors que d'autres appliquent .upper() (dashboard_support). Cette
# divergence silencieuse a deja masque des etats FAILED dans la couche
# perceptual_support. Centraliser ici garantit un comportement uniforme
# et robuste a un payload externe en lowercase ou avec espaces.
def probe_quality_is_failed(value: Any) -> bool:
    """Retourne True si la valeur probe_quality represente l'etat FAILED.

    Tolere None, chaines avec espaces et casse mixte. Toute valeur non
    interpretable comme str renvoie False (statut considere inconnu, donc
    pas FAILED). La comparaison reste case-insensitive pour proteger les
    callsites UI contre un payload serialise avec variation de casse.

    :param value: valeur brute lue depuis NormalizedProbe.probe_quality ou
                  un dict serialise (potentiellement None ou vide).
    :return: True ssi la valeur normalisee == PROBE_QUALITY_FAILED.
    """
    if value is None:
        return False
    try:
        return str(value).strip().upper() == PROBE_QUALITY_FAILED
    except (TypeError, ValueError):
        return False


def probe_quality_is_partial_or_failed(value: Any) -> bool:
    """Retourne True si probe_quality vaut PARTIAL ou FAILED (case-insensitive).

    Sert aux consommateurs (dashboard, rapports) qui groupent les deux etats
    "donnees incompletes" pour l'affichage et la detection d'anomalies.
    """
    if value is None:
        return False
    try:
        normalized = str(value).strip().upper()
    except (TypeError, ValueError):
        return False
    return normalized in {PROBE_QUALITY_PARTIAL, PROBE_QUALITY_FAILED}


# VO-D-1 (2026-06-01) : StrEnum OpType pour typer fortement les valeurs
# canoniques RENAME/MOVE/NOOP du champ RenameProposal.op_type.
#
# StrEnum (Python 3.11+) garantit l'equality avec str :
#     OpType.RENAME == "RENAME"  # True
#     isinstance(OpType.RENAME, str)  # True
#
# Cela preserve la backward compat absolue : tout code existant qui
# manipulait des litterals "RENAME"/"MOVE"/"NOOP" ou les constantes
# OP_TYPE_* continue de fonctionner sans modification.
class OpType(StrEnum):
    """Type d'operation atomique pour RenameProposal.

    Aligne sur le contrat UPPERCASE journal/apply (move_journal + apply_audit
    utilisent MOVE_FILE/MOVE_DIR/MKDIR/QUARANTINE_*/UNDO_*).

    StrEnum implique str equality : OpType.RENAME == "RENAME" -> True.
    """

    RENAME = "RENAME"
    MOVE = "MOVE"
    NOOP = "NOOP"

    @classmethod
    def from_str(cls, value: str) -> "OpType":
        """Convert a string to OpType, supporting legacy lowercase values.

        Ne couvre QUE le vocabulaire RenameProposal (RENAME/MOVE/NOOP), pas
        celui du journal/apply (MOVE_FILE/MOVE_DIR/MKDIR/QUARANTINE_*/UNDO_*).
        Pour mapper RenameProposal -> journal, voir to_journal_op_type().

        :param value: chaine source (sensible a la casse normalisee)
        :raises ValueError: si la valeur n'est pas un OpType valide
        """
        normalized = value.upper().strip()
        try:
            return cls(normalized)
        except ValueError as e:
            raise ValueError(
                f"Unknown OpType: {value!r}, expected one of "
                f"{[m.value for m in cls]} "
                f"(vocabulaire RenameProposal, pas journal/apply : "
                f"pour MOVE_FILE/MOVE_DIR/MKDIR/QUARANTINE_* voir "
                f"to_journal_op_type())"
            ) from e

    @classmethod
    def try_from_str(cls, value: str) -> Optional["OpType"]:
        """Mode tolerant : retourne None si la valeur n'est pas un OpType valide.

        Utile lorsque le vocabulaire d'entree melange RenameProposal et journal
        (MOVE_FILE/MOVE_DIR/etc.) et que l'appelant veut detecter quel
        vocabulaire est en jeu sans crash.

        :param value: chaine source (sensible a la casse normalisee)
        :return: OpType correspondant ou None si non match
        """
        if value is None:
            return None
        try:
            return cls.from_str(value)
        except (ValueError, AttributeError):
            return None

    def to_journal_op_type(self, is_dir: bool = False) -> str:
        """Mappe l'OpType RenameProposal vers le vocabulaire journal/apply.

        Le journal/apply (move_journal + apply_audit) utilise un vocabulaire
        plus granulaire que RenameProposal :
            - RenameProposal.RENAME / MOVE -> MOVE_FILE (ou MOVE_DIR si is_dir)
            - RenameProposal.NOOP          -> NOOP (conserve, n'est pas journalise
              comme MOVE_FILE car aucune operation reelle)

        Ce mapping NE COUVRE PAS QUARANTINE_FILE / QUARANTINE_DIR / MKDIR /
        UNDO_*, qui sont produits directement par les helpers d'infra
        (quarantine_file, ensure_dir, undo_*) sans passer par RenameProposal.

        :param is_dir: True si la cible est un repertoire (rename de dossier)
        :return: vocabulaire journal ("MOVE_FILE" | "MOVE_DIR" | "NOOP")
        """
        if self is OpType.NOOP:
            return "NOOP"
        return "MOVE_DIR" if is_dir else "MOVE_FILE"


# Vocabulaire journal/apply (move_journal + apply_audit). Diverge volontairement
# du vocabulaire domain (OpType RENAME/MOVE/NOOP) car le journal trace plus de
# types d'operation que ce que RenameProposal exprime. Cette divergence est
# DOCUMENTEE et intentionnelle : domain decrit l'intention, infra trace
# l'execution reelle (deplacements de fichiers, repertoires, quarantaines).
#
# Pour mapper domain -> journal, utiliser OpType.to_journal_op_type().
JOURNAL_OP_MOVE_FILE: str = "MOVE_FILE"
JOURNAL_OP_MOVE_DIR: str = "MOVE_DIR"
JOURNAL_OP_MKDIR: str = "MKDIR"
JOURNAL_OP_QUARANTINE_FILE: str = "QUARANTINE_FILE"
JOURNAL_OP_QUARANTINE_DIR: str = "QUARANTINE_DIR"
JOURNAL_OP_VALUES = frozenset({
    JOURNAL_OP_MOVE_FILE,
    JOURNAL_OP_MOVE_DIR,
    JOURNAL_OP_MKDIR,
    JOURNAL_OP_QUARANTINE_FILE,
    JOURNAL_OP_QUARANTINE_DIR,
})


# VN-F.4 (2026-06-01) : OpType canonique UPPERCASE pour aligner RenameProposal
# avec le contrat journal/apply (move_journal + apply_audit utilisent
# MOVE_FILE/MOVE_DIR/MKDIR/QUARANTINE_*/UNDO_*). Les anciens callsites tests
# qui utilisaient "rename"/"move"/"noop" doivent migrer vers ces constantes.
#
# VO-D-1 : ces constantes sont conservees comme alias backward compat,
# derives de OpType (single source of truth). Toute nouvelle utilisation
# doit prefere OpType.RENAME / OpType.MOVE / OpType.NOOP.
OP_TYPE_RENAME: str = OpType.RENAME.value  # backward compat alias
OP_TYPE_MOVE: str = OpType.MOVE.value  # backward compat alias
OP_TYPE_NOOP: str = OpType.NOOP.value  # backward compat alias
OP_TYPE_VALUES = frozenset({OP_TYPE_RENAME, OP_TYPE_MOVE, OP_TYPE_NOOP})

__all__ = [
    "PROBE_QUALITY_FULL",
    "PROBE_QUALITY_PARTIAL",
    "PROBE_QUALITY_FAILED",
    # BUG-018 (hotfix1) : helpers centralises probe_quality (case-insensitive).
    "probe_quality_is_failed",
    "probe_quality_is_partial_or_failed",
    "OpType",
    "OP_TYPE_RENAME",
    "OP_TYPE_MOVE",
    "OP_TYPE_NOOP",
    "OP_TYPE_VALUES",
    # BUG-016 (hotfix1) : vocabulaire journal/apply expose et documente.
    "JOURNAL_OP_MOVE_FILE",
    "JOURNAL_OP_MOVE_DIR",
    "JOURNAL_OP_MKDIR",
    "JOURNAL_OP_QUARANTINE_FILE",
    "JOURNAL_OP_QUARANTINE_DIR",
    "JOURNAL_OP_VALUES",
    "NormalizedProbe",
    # Vague M (M-05) : extensions optionnelles, non utilisees ailleurs en
    # production a cette etape. Disponibles pour les vagues suivantes.
    "ProbeSources",
    "RenameProposal",
    "ProbeResult",
]


@dataclass
class NormalizedProbe:
    path: str
    container: Optional[str] = None
    container_title: Optional[str] = None
    duration_s: Optional[float] = None
    video: Dict[str, Any] = field(default_factory=dict)
    audio_tracks: List[Dict[str, Any]] = field(default_factory=list)
    subtitles: List[Dict[str, Any]] = field(default_factory=list)
    # Source par champ (mediainfo / ffprobe / mediainfo+ffprobe / none)
    sources: Dict[str, Any] = field(default_factory=dict)
    probe_quality: str = PROBE_QUALITY_FAILED
    probe_quality_reasons: List[str] = field(default_factory=list)
    messages: List[str] = field(default_factory=list)

    # Fix audit 2026-05-25 (v1.5.5) Vague K : extension "NFO complet"
    # Champs additionnels extraits depuis ffprobe pour permettre la generation
    # d'un fichier NFO complet (containerextended, chapitres, encoder, bitrate
    # global, sample_rate audio, dispositions sous-titres, etc.).
    # Tous les champs ci-dessous sont OPTIONNELS et n'affectent pas la
    # retro-compat : les anciens consommateurs lisent toujours `video`,
    # `audio_tracks`, `subtitles` (formats inchanges, simplement enrichis).
    container_format_long: Optional[str] = None  # "matroska,webm" complet
    container_size_bytes: Optional[int] = None  # taille du fichier
    container_bit_rate: Optional[int] = None  # global, bits/s
    container_encoder: Optional[str] = None  # writing application
    container_creation_time: Optional[str] = None  # ISO8601 si dispo
    chapters: List[Dict[str, Any]] = field(default_factory=list)

    # BUG-008-COMPLEMENT (hotfix1) : metadonnees enrichies optionnelles pour
    # support edition (Director's Cut, Extended, Theatrical, etc.) et
    # appartenance a une collection TMDb (saga / franchise). Tous deux
    # OPTIONNELS pour preserver la backward compat absolue : les anciens
    # consommateurs ignorent ces champs et la signature minimale
    # NormalizedProbe(path=...) continue de fonctionner.
    edition: Optional[str] = None  # "Director's Cut", "Extended", etc.
    tmdb_collection_id: Optional[str] = None  # id TMDb de la collection/saga

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Vague M (M-05) : EXTENSIONS dataclasses
# ---------------------------------------------------------------------------
# Ces types sont ajoutes pour preparer les vagues suivantes (suivi piste-par-
# piste des sources, propositions de renommage typees, wrapper resultat probe).
# Ils sont OPTIONNELS et n'affectent ni NormalizedProbe ni les callsites
# existants. Aucun module en production ne les consomme a cette vague.
# ---------------------------------------------------------------------------


@dataclass
class ProbeSources:
    """Tracking piste-par-piste des sources de metadonnees probe.

    Permet de savoir, pour chaque sous-element (audio, video, sous-titres),
    quelle source (mediainfo / ffprobe / override manuel) a fourni quel champ.

    Le tracking par piste audio est stocke dans `audio_tracks` : un dict
    indexe par index de piste (int), valeur = dict {field_name: source_name}.

    Invariant : si manual_override est False, AU MOINS une source (mediainfo
    ou ffprobe) doit etre True. Sinon le ProbeSources est invalide car il
    indique qu'aucune metadonnee n'a ete extraite.
    """

    mediainfo: bool = False
    ffprobe: bool = False
    manual_override: bool = False
    # Tracking par piste : audio_tracks[idx][field] = source_name
    audio_tracks: Dict[int, Dict[str, str]] = field(default_factory=dict)
    video: Dict[str, str] = field(default_factory=dict)
    subtitles: Dict[int, Dict[str, str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.manual_override and not (self.mediainfo or self.ffprobe):
            raise ValueError(
                "ProbeSources invalide : au moins une source "
                "(mediainfo, ffprobe) doit etre True si manual_override est False."
            )

    def merge_audio_track(self, idx: int, field_name: str, source: str) -> None:
        """Enregistre la source d'un champ pour une piste audio donnee.

        :param idx: index de la piste audio (0-based)
        :param field_name: nom du champ (ex: "codec", "channels", "language")
        :param source: identifiant de la source ("mediainfo", "ffprobe",
                       "mediainfo+ffprobe", "manual", "none")
        """
        if idx < 0:
            raise ValueError(f"idx doit etre >= 0, recu {idx}")
        if not field_name:
            raise ValueError("field_name ne peut pas etre vide")
        if not source:
            raise ValueError("source ne peut pas etre vide")
        track = self.audio_tracks.setdefault(idx, {})
        track[field_name] = source

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RenameProposal:
    """Proposition de renommage / deplacement d'un fichier.

    Represente une operation atomique (rename ou move) telle que proposee
    par le moteur de naming, avant validation/execution. Sert d'unite de
    transport entre domain (decision) et infra (execution + audit).
    """

    src_path: str
    target_path: str
    # VN-F.4 : valeurs canoniques OP_TYPE_RENAME / OP_TYPE_MOVE / OP_TYPE_NOOP
    # (UPPERCASE, aligne sur le contrat journal/apply MOVE_FILE/MOVE_DIR/MKDIR).
    # Voir cinesort.domain.probe_models.OP_TYPE_VALUES.
    #
    # VO-D-1 : prefere OpType (StrEnum) pour les nouveaux callsites :
    #     op_type=OpType.RENAME  # recommande
    # L'annotation reste `str` pour preserver la backward compat ABSOLUE
    # (anciens callsites passant "RENAME" directement). StrEnum IS str, donc
    # OpType.RENAME est assignable a un champ typed str sans coercion.
    op_type: str  # "RENAME" | "MOVE" | "NOOP" (prefere OpType StrEnum)
    no_op: bool = False
    reason: str = ""
    # Champs additionnels optionnels pour enrichissement futur
    confidence: Optional[float] = None
    source: Optional[str] = None  # "auto" | "manual" | "external"
    alternatives: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialisation API-friendly (roundtrip via from_dict).

        VO-D-2 : normalise op_type en str pur (au cas ou un appelant a fourni
        OpType.RENAME directement) pour preserver l'invariant json-safe.
        StrEnum IS str donc la coercion est cosmetique mais elle aligne le
        type runtime sur l'annotation declaree (str).
        """
        d = asdict(self)
        # Normalise OpType -> str pur (json-safe). StrEnum.__str__ retourne
        # la valeur (ex: "RENAME"), pas "OpType.RENAME", grace a StrEnum.
        op = d.get("op_type")
        if isinstance(op, OpType):
            d["op_type"] = str(op)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RenameProposal":
        """Reconstruction depuis un dict (roundtrip de to_dict).

        Tolere les champs manquants en utilisant les defauts du dataclass.
        Les champs inconnus sont ignores silencieusement (forward-compat).

        BUG-020 (hotfix1) : normalise op_type via OpType.from_str pour
        accepter les valeurs lowercase pre-VN-F.4 ("rename"/"move"/"noop")
        et garantir un roundtrip propre. Si la valeur est inconnue mais
        non vide, on laisse passer la valeur brute pour preserver la
        backward compat absolue (un appelant peut avoir stocke un op_type
        custom). Si la valeur est invalide pour OpType, on conserve la
        chaine telle quelle apres upper-strip basique.
        """
        known = {
            "src_path",
            "target_path",
            "op_type",
            "no_op",
            "reason",
            "confidence",
            "source",
            "alternatives",
            "reasons",
        }
        filtered = {k: v for k, v in data.items() if k in known}
        # Normalise op_type via OpType.from_str (upper-strip + validation).
        # Fallback : si la valeur est invalide pour OpType, on garde la chaine
        # brute apres normalisation cosmetique (upper-strip) pour eviter de
        # casser un appelant qui aurait stocke un vocabulaire custom.
        raw_op = filtered.get("op_type")
        if isinstance(raw_op, str):
            normalized = OpType.try_from_str(raw_op)
            if normalized is not None:
                filtered["op_type"] = normalized
            else:
                # Conserve la valeur brute apres upper-strip pour backward compat.
                filtered["op_type"] = raw_op.upper().strip()
        return cls(**filtered)


@dataclass
class ProbeResult:
    """Wrapper composite : NormalizedProbe + tracking sources + raw payloads.

    Permet aux consommateurs avances (UI debug, audit, replay) d'acceder aux
    donnees brutes mediainfo/ffprobe AVANT normalisation, tout en exposant
    le `NormalizedProbe` standard via l'attribut `normalized`.

    Retro-compat : ce type est purement additif. ProbeService.probe_file
    continue de retourner NormalizedProbe (signature inchangee). Les nouveaux
    helpers `probe_file_with_sources` retourneront ProbeResult.
    """

    normalized: NormalizedProbe
    sources: ProbeSources
    raw_mediainfo: Optional[Dict[str, Any]] = None
    raw_ffprobe: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "normalized": self.normalized.to_dict(),
            "sources": self.sources.to_dict(),
            "raw_mediainfo": self.raw_mediainfo,
            "raw_ffprobe": self.raw_ffprobe,
        }
