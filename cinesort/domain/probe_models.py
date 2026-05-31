from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

PROBE_QUALITY_FULL = "FULL"
PROBE_QUALITY_PARTIAL = "PARTIAL"
PROBE_QUALITY_FAILED = "FAILED"

__all__ = [
    "PROBE_QUALITY_FULL",
    "PROBE_QUALITY_PARTIAL",
    "PROBE_QUALITY_FAILED",
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
    op_type: str  # "rename" | "move" | "noop"
    no_op: bool = False
    reason: str = ""
    # Champs additionnels optionnels pour enrichissement futur
    confidence: Optional[float] = None
    source: Optional[str] = None  # "auto" | "manual" | "external"
    alternatives: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialisation API-friendly (roundtrip via from_dict)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RenameProposal":
        """Reconstruction depuis un dict (roundtrip de to_dict).

        Tolere les champs manquants en utilisant les defauts du dataclass.
        Les champs inconnus sont ignores silencieusement (forward-compat).
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
