"""V2.1 — Types polymorphiques PerceptualReport | QualityReport (domain pur).

Memoire critique CRITIQUE :
- "perceptual!=quality (reports separes en memoire et stockage)"
- Ces deux types DOIVENT rester distincts : memes champs, semantique
  differente. La discrimination se fait via `kind: Literal["perceptual", "quality"]`.

Architecture (memoire : "domain ne PEUT PAS importer app/infra/ui") :
- Ce module n'importe QUE pydantic + stdlib + cinesort.domain.*.
- Aucun import de cinesort.app / cinesort.infra / cinesort.ui — verifie
  par import-linter `domain_pure`.

Usage typique cote app/infra :
    >>> from cinesort.domain.report_types import REPORT_ADAPTER, AnyReport
    >>> data = {"kind": "perceptual", "row_id": "r1", "visual_score": 88, ...}
    >>> report = REPORT_ADAPTER.validate_python(data)
    >>> assert isinstance(report, PerceptualReport)
    >>>
    >>> # Export JSON Schema (consomme par scripts/generate_api_schema.py)
    >>> schema = REPORT_ADAPTER.json_schema()

BACKWARD COMPAT : `extra="allow"` partout — le code legacy qui ecrit des
champs custom dans perceptual_reports / quality_reports continue de
fonctionner sans modification.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _ReportBase(BaseModel):
    """Base commune aux deux types de rapports (champs partages stricts)."""

    model_config = ConfigDict(extra="allow")

    row_id: str = Field(..., min_length=1, description="Identifiant de la row du run associee.")
    run_id: Optional[str] = Field(
        default=None,
        description="Identifiant du run (None si rapport orphelin / pre-persistance).",
    )
    generated_ts: Optional[float] = Field(
        default=None,
        description="Timestamp UNIX (s) de generation du rapport.",
    )


class PerceptualReport(_ReportBase):
    """Rapport PERCEPTUEL (analyse visuelle/audio multi-frames).

    Stocke dans la table `perceptual_reports`. Source : `cinesort.domain.perceptual.*`.
    NE PAS confondre avec QualityReport (table separee).
    """

    kind: Literal["perceptual"] = "perceptual"

    # Champs visuels (resumes — pas la totalite de VideoPerceptual).
    visual_score: int = Field(default=0, ge=0, le=100)
    visual_tier: str = Field(
        default="degrade",
        description="Tier visuel canonique (excellent / bon / moyen / degrade).",
    )
    blockiness_mean: float = Field(default=0.0, ge=0.0)
    blur_mean: float = Field(default=0.0, ge=0.0)
    banding_mean: float = Field(default=0.0, ge=0.0)

    # §13/§7 v7.5.0 — flags integrite/upscale.
    ssim_self_ref: float = Field(default=-1.0)  # -1 = non applicable
    upscale_verdict: str = Field(default="unknown")
    upscale_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    fake_4k_verdict_combined: str = Field(default="unknown")

    # Eventuels audio_fingerprints / vision_embedding sont dans `extras`
    # (preserves via `extra="allow"` du base config).


class QualityReport(_ReportBase):
    """Rapport QUALITE (score derive metadata + probe, sans frames).

    Stocke dans la table `quality_reports`. Source : `cinesort.domain.quality_score`,
    `cinesort.domain.probe_models`. NE PAS confondre avec PerceptualReport.
    """

    kind: Literal["quality"] = "quality"

    quality_score: int = Field(default=0, ge=0, le=100)
    quality_tier: str = Field(
        default="degrade",
        description="Tier qualite canonique (excellent / bon / moyen / degrade).",
    )

    # Composantes du score (issues de quality_score.py).
    codec_rank: int = Field(default=0)
    resolution_rank: int = Field(default=0)
    audio_rank: int = Field(default=0)
    bitrate_score: int = Field(default=0)

    # Probe quality (FULL / PARTIAL / FAILED — cf probe_models).
    probe_quality: str = Field(default="FULL")

    # Anomalies/warnings issues du quality_audit_support.
    anomalies: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Union discriminee + TypeAdapter (Pydantic v2.13 pattern recommande pour
# parsing polymorphique sans heritage Python explicite).
# ---------------------------------------------------------------------------
AnyReport = Annotated[
    Union[PerceptualReport, QualityReport],
    Field(discriminator="kind"),
]

# TypeAdapter (singleton module-level) : evite la recompilation du schema
# polymorphique a chaque appel. Utilise par :
#   - scripts/generate_api_schema.py (json_schema export)
#   - run_facade (validation passive, log warning si fail)
#   - infra (deserialisation des rangees DB perceptual_reports/quality_reports)
REPORT_ADAPTER: "TypeAdapter[AnyReport]" = TypeAdapter(AnyReport)


def parse_report_safe(data: Dict[str, Any]) -> Optional[AnyReport]:
    """Parse un rapport polymorphique sans lever d'exception.

    Backward compat : retourne `None` si la validation echoue. Le caller
    peut alors retomber sur la shape legacy `dict[str, Any]`. Ne logge rien
    ici (le caller decide selon le contexte / feature flag).

    :param data: dict serialise (DB row, payload API, JSON).
    :return: Une instance PerceptualReport ou QualityReport, ou None si fail.
    """
    try:
        return REPORT_ADAPTER.validate_python(data)
    except Exception:  # noqa: BLE001 — backward compat : on ne raise jamais ici.
        return None
