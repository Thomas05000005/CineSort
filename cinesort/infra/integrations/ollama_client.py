"""Client Ollama minimal — scaffold V4.1 enrichissement IA.

Bounded context : "AI enrichment" (synopsis/tags generes par LLM local).

Strategie scaffold (cf SimilarFilmsFacade V3.3) :
- Le client est INSTALLE mais le feature flag global ai_enrichment est OFF.
- is_available() pingue http://localhost:11434/api/tags pour detecter
  l'instance Ollama locale ; toute erreur (ConnectionError, timeout,
  status != 200) renvoie False sans crasher.
- generate_synopsis(title, year) et generate_tags(metadata) renvoient un
  payload structure { ok, generated, ai_generated: True, source: "ollama",
  model, ...} ou en cas d'erreur { ok: False, reason, ai_generated: False }.
- Aucune execution effective de prompts dans cette PR : les methodes posent
  les contracts d'appel et le routage HTTP. L'integration runtime arrivera
  une fois le bundle valide (PAS DE DL au 1er usage).

Modeles par defaut :
- llama3.2:3b  : leger (2 Go RAM), reponse rapide, qualite suffisante pour
  synopsis court (1 paragraphe).
- qwen2.5:7b   : meilleure qualite, ~5 Go RAM, pour tags semantiques fins.

Memoires critiques :
- perceptual != quality : les tags generes ici sont SEMANTIQUES (genre,
  ambiance, tropes), DISTINCTS du quality score et du perceptual hash.
- Backward compat ABSOLUE : si Ollama indisponible, l'enrichment_facade
  renvoie un degraded payload, jamais d'exception non geree.
- Code robuste aux binaires absents : ollama est un binaire externe
  totalement optionnel.

Architecture (import-linter) :
- domain ne peut PAS importer ce module (infra)
- app/enrichment_facade.py importe ce module (app -> infra OK)
- ui/api peut importer via enrichment_facade (ui -> app OK)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import requests

from cinesort.infra._http_utils import make_session_with_retry
from cinesort.infra.integration_errors import IntegrationError
from cinesort.infra.network_utils import is_safe_external_url

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2:3b"
ALT_OLLAMA_MODEL = "qwen2.5:7b"
# Temperature=0 : reponses deterministes, requis pour reproductibilite
# des enrichissements (un meme film doit produire le meme synopsis).
DEFAULT_TEMPERATURE = 0.0
DEFAULT_TIMEOUT_S = 30.0


class OllamaError(IntegrationError):
    """Erreur liee a l'API Ollama locale.

    Herite de IntegrationError (BUG-1 v7.8.0) pour permettre un catch
    uniforme cross-clients sans recourir a `except Exception`.
    """


# JSON schema strict pour la generation de synopsis. Ollama accepte le
# parametre `format` pour contraindre la sortie a un JSON valide.
SYNOPSIS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "synopsis": {"type": "string", "minLength": 20, "maxLength": 800},
        "tone": {"type": "string"},
    },
    "required": ["synopsis"],
}

TAGS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 10,
        },
    },
    "required": ["tags"],
}


def _normalize_endpoint(endpoint: str) -> str:
    """Normalise l'URL Ollama (strip, trailing slash, validation SSRF).

    Comme JellyfinClient._normalize_url (cf issue #70), refuse les URL
    pointant vers les endpoints cloud metadata. Leve OllamaError si
    invalide.
    """
    endpoint = (endpoint or "").strip().rstrip("/")
    if endpoint and "://" not in endpoint:
        endpoint = f"http://{endpoint}"
    if endpoint:
        ok, reason = is_safe_external_url(endpoint)
        if not ok:
            raise OllamaError(f"URL Ollama refusee : {reason}")
    return endpoint or DEFAULT_OLLAMA_ENDPOINT


class OllamaClient:
    """Client pour l'API REST Ollama locale (scaffold V4.1).

    Args:
        endpoint: URL de l'instance Ollama. Defaut http://localhost:11434.
        model: Nom du modele LLM. Defaut llama3.2:3b (rapide), alternative
            qwen2.5:7b (qualite superieure).
        timeout_s: Timeout reseau par appel (defaut 30s, max 120s).
        temperature: Defaut 0.0 (deterministe).
    """

    def __init__(
        self,
        endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
        model: str = DEFAULT_OLLAMA_MODEL,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> None:
        self.endpoint = _normalize_endpoint(endpoint)
        self.model = (model or DEFAULT_OLLAMA_MODEL).strip()
        self.timeout_s = max(1.0, min(120.0, float(timeout_s)))
        self.temperature = max(0.0, min(1.0, float(temperature)))
        # Session avec retry/backoff (ID-ROB-001). Ollama local renvoie
        # parfois 503 pendant le chargement du modele en RAM (premiere
        # requete) — le retry absorbe ce cas.
        self._session = make_session_with_retry(
            user_agent="CineSort/7.7 OllamaClient",
            max_attempts=3,
            backoff_base=0.5,
        )

    # ---------- Health ----------

    def is_available(self) -> bool:
        """Pingue Ollama via GET /api/tags. Retourne True si HTTP 200.

        Ne leve jamais : toute erreur (ConnectionError, timeout, status
        != 200) renvoie False. Le caller utilise ce check pour decider
        si l'enrichment doit etre tente (fail-soft).
        """
        try:
            resp = self._session.get(
                f"{self.endpoint}/api/tags",
                timeout=min(5.0, self.timeout_s),
            )
            return resp.status_code == 200
        except (requests.RequestException, OllamaError) as exc:
            logger.debug("Ollama indisponible : %s", exc)
            return False

    # ---------- Generation ----------

    def generate_synopsis(self, title: str, year: Optional[int] = None) -> Dict[str, Any]:
        """Genere un synopsis court pour (title, year) via le LLM.

        Returns:
            { ok: True, generated: str, ai_generated: True, source:
              "ollama", model: str } en cas de succes.
            { ok: False, reason: str, ai_generated: False } sinon.
        """
        if not (title or "").strip():
            return {"ok": False, "reason": "empty_title", "ai_generated": False}
        prompt = self._build_synopsis_prompt(title.strip(), year)
        return self._invoke(prompt, schema=SYNOPSIS_SCHEMA, key="synopsis")

    def generate_tags(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Genere une liste de tags semantiques a partir de metadata.

        Args:
            metadata: dict { title, year, genres, runtime, ... } — au moins
                title est requis.

        Returns:
            { ok: True, generated: List[str], ai_generated: True, ... }
            ou { ok: False, reason, ai_generated: False }.
        """
        title = (metadata or {}).get("title", "").strip()
        if not title:
            return {"ok": False, "reason": "empty_title", "ai_generated": False}
        prompt = self._build_tags_prompt(metadata)
        result = self._invoke(prompt, schema=TAGS_SCHEMA, key="tags")
        return result

    # ---------- Internes ----------

    def _invoke(
        self,
        prompt: str,
        *,
        schema: Dict[str, Any],
        key: str,
    ) -> Dict[str, Any]:
        """Appelle POST /api/generate avec le schema JSON strict en `format`.

        Renvoie un payload normalise. Toute erreur reseau ou JSON est
        rattrapee et convertie en { ok: False, reason }.
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": schema,
            "options": {"temperature": self.temperature},
        }
        try:
            resp = self._session.post(
                f"{self.endpoint}/api/generate",
                json=payload,
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            logger.warning("Ollama generate echec reseau : %s", exc)
            return {"ok": False, "reason": f"network_error: {exc}", "ai_generated": False}
        if resp.status_code != 200:
            return {
                "ok": False,
                "reason": f"http_{resp.status_code}",
                "ai_generated": False,
            }
        try:
            data = resp.json()
            raw = data.get("response", "")
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning("Ollama JSON parse echec : %s", exc)
            return {"ok": False, "reason": "invalid_json", "ai_generated": False}
        generated = parsed.get(key)
        if generated is None:
            return {"ok": False, "reason": "missing_key", "ai_generated": False}
        return {
            "ok": True,
            "generated": generated,
            "ai_generated": True,
            "source": "ollama",
            "model": self.model,
        }

    @staticmethod
    def _build_synopsis_prompt(title: str, year: Optional[int]) -> str:
        year_part = f" ({year})" if year else ""
        return (
            "Tu es un cinephile francophone. Redige un synopsis court (3-5 "
            f"phrases, FR) pour le film '{title}'{year_part}. Reponds en JSON "
            "strict : { \"synopsis\": \"...\" }."
        )

    @staticmethod
    def _build_tags_prompt(metadata: Dict[str, Any]) -> str:
        compact = json.dumps(
            {k: metadata.get(k) for k in ("title", "year", "genres", "runtime") if metadata.get(k)},
            ensure_ascii=False,
        )
        return (
            "Analyse ces metadonnees de film et propose 5 a 8 tags semantiques "
            "FR (ambiance, tropes, sous-genres). Pas de spoiler. "
            f"Metadonnees : {compact}. Reponds en JSON strict : "
            "{ \"tags\": [\"...\", \"...\"] }."
        )
