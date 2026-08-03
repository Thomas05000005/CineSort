"""EnrichmentFacade : bounded context "AI enrichment" (scaffold V4.1).

Strategie scaffold (cf SimilarFilmsFacade V3.3) :
- Feature flag global ai_enrichment = False : tant que la stack Ollama
  n'est pas validee end-to-end, tous les appels renvoient un payload
  degraded explicite.
- enrichment_for_film(film_id) est async : permet d'enchainer plusieurs
  prompts (synopsis + tags) en parallele une fois le flag ON.
- Le badge ai_generated=True est PROPAGE jusqu'a l'UI : tout contenu
  genere par LLM doit etre visuellement distinct (cf
  web/dashboard/views/enrichment.js, badge orange "IA generated").

Memoires critiques :
- domain ne peut PAS importer ce module (couche app)
- backward compat ABSOLUE : flag OFF = legacy unchanged
- perceptual != quality : enrichment != analyse perceptuelle
- Actions dangereuses ("Appliquer toutes les suggestions IA") : modale
  de confirmation avec liste, consequence, delai 3s si > 50 elements
  (gere cote UI, cf web/dashboard/views/enrichment.js)
- DPAPI : aucun secret a chiffrer ici (Ollama est local, pas d'API key)

Architecture (import-linter) :
- app -> infra OK (importe OllamaClient)
- domain ne peut PAS importer ce module
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from cinesort.infra.integrations.ollama_client import (
    DEFAULT_OLLAMA_ENDPOINT,
    DEFAULT_OLLAMA_MODEL,
    OllamaClient,
)

logger = logging.getLogger(__name__)


# Feature flag global. Mettre True une fois la stack Ollama validee
# (modele bundle, prompts evalues, perf benchmark). Cf issue
# docs/internal/REFACTOR_PLAN_V4_1.md (TBD).
AI_ENRICHMENT_FEATURE_FLAG: bool = False


def _disabled_payload(reason: str = "feature_flag_disabled") -> Dict[str, Any]:
    """Payload de degradation lorsque ai_enrichment est OFF ou indisponible.

    Forme stable :
        { ok: False, reason: str, ai_generated: False, synopsis: None,
          tags: [] }

    L'UI s'appuie sur `ai_generated` pour decider d'afficher le badge
    orange. False ici garantit que rien de visuel ne suggere du contenu IA.
    """
    return {
        "ok": False,
        "reason": reason,
        "ai_generated": False,
        "synopsis": None,
        "tags": [],
    }


def get_enrichment_status() -> Dict[str, Any]:
    """Etat de la feature ai_enrichment (introspection pour la UI).

    Renvoie :
        { feature_flag: bool, ollama_available: bool, model: str,
          endpoint: str }
    """
    available = False
    if AI_ENRICHMENT_FEATURE_FLAG:
        try:
            client = OllamaClient()
            available = client.is_available()
        except Exception as exc:  # noqa: BLE001 — scaffold robuste
            logger.debug("OllamaClient.is_available a leve : %s", exc)
            available = False
    return {
        "feature_flag": AI_ENRICHMENT_FEATURE_FLAG,
        "ollama_available": available,
        "model": DEFAULT_OLLAMA_MODEL,
        "endpoint": DEFAULT_OLLAMA_ENDPOINT,
    }


async def enrichment_for_film(
    film_id: int,
    *,
    metadata: Optional[Dict[str, Any]] = None,
    client: Optional[OllamaClient] = None,
) -> Dict[str, Any]:
    """Enrichit un film via LLM local : synopsis + tags semantiques.

    Async pour permettre, lorsque le flag sera ON, de paralleliser
    synopsis et tags (via asyncio.to_thread car le client requests est
    sync). Pour l'instant le flag est OFF donc on retourne immediatement.

    Args:
        film_id: identifiant du film cible (clef BDD).
        metadata: { title, year, genres, runtime, ... }. Si None, le caller
            est responsable de la lookup BDD ulterieurement.
        client: injection pour les tests.

    Returns:
        { ok: bool, film_id: int, ai_generated: bool, synopsis: str|None,
          tags: List[str], model: str|None, reason: str|None }
    """
    if not AI_ENRICHMENT_FEATURE_FLAG:
        payload = _disabled_payload("feature_flag_disabled")
        payload["film_id"] = film_id
        return payload

    metadata = metadata or {}
    if not metadata.get("title"):
        payload = _disabled_payload("missing_metadata")
        payload["film_id"] = film_id
        return payload

    cli = client or OllamaClient()
    if not cli.is_available():
        payload = _disabled_payload("ollama_unavailable")
        payload["film_id"] = film_id
        return payload

    # Scaffold : appels sync pour l'instant. Lors du runtime V4.1, wrapper
    # dans asyncio.to_thread() pour paralleliser proprement.
    synopsis_res = cli.generate_synopsis(metadata.get("title", ""), metadata.get("year"))
    tags_res = cli.generate_tags(metadata)

    return {
        "ok": bool(synopsis_res.get("ok") or tags_res.get("ok")),
        "film_id": film_id,
        "ai_generated": True,
        "synopsis": synopsis_res.get("generated") if synopsis_res.get("ok") else None,
        "tags": tags_res.get("generated", []) if tags_res.get("ok") else [],
        "model": cli.model,
        "reason": None,
    }
