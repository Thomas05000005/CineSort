"""Facade de stockage des secrets settings : routage NG / legacy.

`save_secret` produit toujours un blob DPAPI-NG (via `dpapi_ng.protect`).
`load_secret` lit indifferemment un blob NG (nouveau format) OU un blob
legacy pre-existant (`local_secret_store.protect_secret`), garantissant la
retro-compat : les cles deja enregistrees dans un settings.json restent
lisibles apres la migration NG (aucune perte de secret).

Les appelants (`ui.api.settings_support`, `infra.integrations.poster_proxy`)
capturent `SecretStorageError` ; sur echec NG (DPAPI indisponible), le chemin
legacy prend le relais cote appelant.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from cinesort.infra import local_secret_store as _dpapi
from cinesort.infra.security import dpapi_ng as _ng


class SecretStorageError(Exception):
    """Echec de protection/dechiffrement d'un secret (DPAPI indisponible,
    blob corrompu, scope CURRENT_USER change...)."""


@dataclass(frozen=True)
class LoadedSecret:
    """Resultat de `load_secret` : la valeur en clair et le schema d'origine."""

    value: str
    scheme: str


def save_secret(purpose: str, raw: str) -> str:
    """Chiffre `raw` en blob DPAPI-NG et retourne son encodage base64.

    Raises:
        SecretStorageError: si DPAPI-NG est indisponible (non-Windows, CNG
            absent). L'appelant retombe alors sur la protection legacy.
    """
    ok, blob_b64, error = _ng.protect(raw, purpose=purpose)
    if not ok:
        raise SecretStorageError(error or "DPAPI-NG indisponible.")
    return blob_b64


def load_secret(purpose: str, blob_b64: str) -> LoadedSecret:
    """Dechiffre un blob NG ou legacy et retourne un `LoadedSecret`.

    Le routage se fait sur le marqueur d'enveloppe NG : present -> chemin NG,
    absent -> chemin legacy (`local_secret_store`).

    Raises:
        SecretStorageError: blob vide, illisible, ou dechiffrement echoue.
    """
    blob_b64 = str(blob_b64 or "").strip()
    if not blob_b64:
        raise SecretStorageError("Blob secret vide.")
    try:
        raw = base64.b64decode(blob_b64.encode("ascii"), validate=True)
    except (TypeError, ValueError) as exc:
        raise SecretStorageError(f"Blob secret illisible: {exc}") from exc

    if _ng.is_dpapi_ng_blob(raw):
        ok, value, error = _ng.unprotect(blob_b64, purpose=purpose)
        scheme = "dpapi_ng"
    else:
        ok, value, error = _dpapi.unprotect_secret(blob_b64, purpose=purpose)
        scheme = _dpapi.WINDOWS_DPAPI_CURRENT_USER
    if not ok:
        raise SecretStorageError(error or "Dechiffrement du secret echoue.")
    return LoadedSecret(value=value, scheme=scheme)
