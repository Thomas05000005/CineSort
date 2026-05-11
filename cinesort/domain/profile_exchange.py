"""P4.3 : import/export de profils qualité — préparation partage communautaire.

Objectif : permettre à un utilisateur d'exporter son profil qualité
(potentiellement calibré via P4.1) pour le partager à un autre, qui
pourra l'importer et l'utiliser.

Format d'échange (JSON structuré) :

    {
      "schema": "cinesort.quality_profile",
      "schema_version": 1,
      "exported_at": "2026-04-22T18:30:00Z",
      "exporter": "CineSort 7.3.0-dev",
      "name": "Ma config cinéma",      # libre, fourni par l'utilisateur
      "author": "anonymous",            # optionnel
      "description": "Profil privilégiant l'audio Atmos et HDR",
      "profile": { ... }                # le profil qualité CineSort tel quel
    }

Le wrapping permet d'ajouter des métadonnées (auteur, description) sans
polluer la structure interne du profil. L'unwrap extrait juste le bloc
`profile` tout en validant la structure.

Garde-fous import :
- Valider `schema == "cinesort.quality_profile"` (rejeter n'importe quel JSON).
- Valider `schema_version` ≤ MAX (refus si trop récent).
- Valider la structure du `profile` via `validate_quality_profile` (déjà fait par quality_score).
- Sanitiser : strip champs inconnus au top-level (évite injection d'extras).
- Borner la taille du JSON (évite DoS par profil géant).

Tout est pur, testable unitairement.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional, Tuple


SCHEMA_NAME = "cinesort.quality_profile"
SCHEMA_VERSION_MAX = 1
MAX_JSON_BYTES = 128 * 1024  # 128 KB — un profil est petit, évite DoS
MAX_STRING_FIELD_LEN = 1024  # anti-injection / anti-DoS


def wrap_profile_for_export(
    profile: Dict[str, Any],
    *,
    name: str = "",
    author: str = "",
    description: str = "",
    exporter: str = "",
) -> Dict[str, Any]:
    """Enveloppe un profil qualité avec metadata pour export.

    Args:
        profile : le dict du profil qualité (tel que retourné par default_quality_profile
                  ou stocké en BDD).
        name/author/description : métadonnées utilisateur (optionnelles).
        exporter : chaîne identifiant l'app (ex: "CineSort 7.3.0-dev").

    Retourne un dict sérialisable JSON.
    """
    if not isinstance(profile, dict):
        raise TypeError("profile must be a dict")
    return {
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION_MAX,
        "exported_at": _iso_now(),
        "exporter": str(exporter or "")[:MAX_STRING_FIELD_LEN],
        "name": str(name or "")[:MAX_STRING_FIELD_LEN],
        "author": str(author or "")[:MAX_STRING_FIELD_LEN],
        "description": str(description or "")[:MAX_STRING_FIELD_LEN],
        "profile": dict(profile),
    }


def serialize_profile_export(wrapped: Dict[str, Any]) -> str:
    """Sérialise un wrapped export en JSON (UTF-8, indenté pour lisibilité humaine)."""
    return json.dumps(wrapped, ensure_ascii=False, indent=2, sort_keys=True)


def parse_and_validate_import(
    content: str,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """Parse et valide un contenu JSON importé.

    Retourne (ok, unwrapped_profile, message_erreur).

    - Si ok == True : unwrapped_profile est le dict du profil prêt à utiliser.
    - Si ok == False : message explique pourquoi.
    """
    if not isinstance(content, str):
        return False, None, "Contenu invalide (attendu : chaîne JSON)."
    raw = content.strip()
    if not raw:
        return False, None, "Contenu vide."
    if len(raw.encode("utf-8")) > MAX_JSON_BYTES:
        return False, None, f"Fichier trop volumineux (max {MAX_JSON_BYTES // 1024} Ko)."

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        return False, None, f"JSON invalide : {exc}"

    if not isinstance(data, dict):
        return False, None, "Le JSON doit être un objet (dict)."

    schema = str(data.get("schema") or "")
    if schema != SCHEMA_NAME:
        return False, None, f"Schéma non reconnu : '{schema}' (attendu : '{SCHEMA_NAME}')."

    version = data.get("schema_version")
    try:
        version_int = int(version)
    except (TypeError, ValueError):
        return False, None, "schema_version manquant ou invalide."
    if version_int > SCHEMA_VERSION_MAX:
        return (
            False,
            None,
            f"schema_version {version_int} trop récent pour cette version de CineSort (max supporté : {SCHEMA_VERSION_MAX}). Mettre à jour l'app.",
        )
    if version_int < 1:
        return False, None, "schema_version doit être ≥ 1."

    profile = data.get("profile")
    if not isinstance(profile, dict):
        return False, None, "Champ 'profile' manquant ou invalide."

    # Validation structure : clés essentielles présentes
    for required in ("weights", "tiers"):
        if not isinstance(profile.get(required), dict):
            return False, None, f"Profil incomplet : '{required}' manquant ou invalide."

    # Validation supplémentaire via le validateur de quality_score (poids
    # normalisés, tiers cohérents, etc.).
    try:
        from cinesort.domain.quality_score import validate_quality_profile

        ok, errors, _normalized = validate_quality_profile(profile)
        if not ok:
            msg = "Profil invalide : " + "; ".join(str(e) for e in (errors or []))
            return False, None, msg[:500]
    except (ImportError, TypeError, ValueError) as exc:
        # Si le validateur crash, on refuse par sécurité
        return False, None, f"Erreur validation : {exc}"

    return True, dict(profile), ""


def extract_import_metadata(content: str) -> Dict[str, Any]:
    """Extrait les métadonnées d'import (pour preview avant appliquer).

    Retourne `{name, author, description, exported_at, exporter, schema_version}`.
    Champs manquants remplacés par chaîne vide. Ne valide PAS la structure
    du profil — c'est pour du preview.
    """
    out = {"name": "", "author": "", "description": "", "exported_at": "", "exporter": "", "schema_version": ""}
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError, TypeError):
        return out
    if not isinstance(data, dict):
        return out
    for k in ("name", "author", "description", "exported_at", "exporter"):
        v = data.get(k)
        if v is not None:
            out[k] = str(v)[:MAX_STRING_FIELD_LEN]
    sv = data.get("schema_version")
    if sv is not None:
        out["schema_version"] = str(sv)
    return out


def _iso_now() -> str:
    """ISO 8601 UTC avec suffix Z."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


__all__ = [
    "SCHEMA_NAME",
    "SCHEMA_VERSION_MAX",
    "MAX_JSON_BYTES",
    "wrap_profile_for_export",
    "serialize_profile_export",
    "parse_and_validate_import",
    "extract_import_metadata",
]
