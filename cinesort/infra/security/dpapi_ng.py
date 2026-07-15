"""Enveloppe DPAPI-NG des secrets CineSort.

Un blob "NG" = marqueur `_NG_MAGIC` suivi de la charge protegee par DPAPI
CURRENT_USER (crypt32). Le marqueur permet a `secret_storage.load_secret`
de distinguer un blob NG d'un blob legacy (produit directement par
`local_secret_store.protect_secret`, qui commence par l'en-tete DPAPI
`01 00 00 00 ...` et donc jamais par `_NG_MAGIC`).

La crypto effective delegue a `local_secret_store` : le format "NG" est ici
une enveloppe versionnee au-dessus du meme DPAPI CURRENT_USER, ce qui
- garde l'invariant "un attaquant qui copie la DB ne lit pas les secrets",
- permet une future bascule vers NCryptProtectSecret (vrai CNG NG) sans
  changer le contrat public (`is_dpapi_ng_blob` / `protect` / `unprotect`).
"""

from __future__ import annotations

import base64
from typing import Tuple

from cinesort.infra import local_secret_store as _dpapi

# Marqueur d'enveloppe NG (CineSort NG v1). N'entre jamais en collision avec
# l'en-tete d'un blob DPAPI legacy, qui debute par `01 00 00 00`.
_NG_MAGIC = b"CSNGv1\x00"


def is_dpapi_ng_blob(raw: bytes) -> bool:
    """True si `raw` (octets decodes) porte le marqueur d'enveloppe NG."""
    return isinstance(raw, (bytes, bytearray)) and bytes(raw).startswith(_NG_MAGIC)


def protect(value: str, *, purpose: str) -> Tuple[bool, str, str]:
    """Chiffre `value` en enveloppe NG. Retourne (ok, blob_b64, error).

    `blob_b64` decode en octets commencant par `_NG_MAGIC` (cf.
    `is_dpapi_ng_blob`). En cas d'indisponibilite DPAPI (non-Windows),
    retourne (False, "", <message>) pour que l'appelant retombe en legacy.
    """
    ok, legacy_b64, error = _dpapi.protect_secret(value, purpose=purpose)
    if not ok:
        return False, "", error
    try:
        payload = base64.b64decode(legacy_b64.encode("ascii"), validate=True)
    except (TypeError, ValueError) as exc:  # pragma: no cover — sortie crypt32 valide
        return False, "", f"Blob legacy illisible: {exc}"
    ng_raw = _NG_MAGIC + payload
    return True, base64.b64encode(ng_raw).decode("ascii"), ""


def unprotect(blob_b64: str, *, purpose: str) -> Tuple[bool, str, str]:
    """Dechiffre un blob NG. Retourne (ok, value, error).

    Ne traite QUE les blobs NG (marqueur present). Un blob legacy renvoie
    (False, "", ...) : le routage legacy est du ressort de
    `secret_storage.load_secret`.
    """
    try:
        raw = base64.b64decode(str(blob_b64 or "").encode("ascii"), validate=True)
    except (TypeError, ValueError) as exc:
        return False, "", f"Blob NG invalide: {exc}"
    if not is_dpapi_ng_blob(raw):
        return False, "", "Blob non-NG (marqueur absent)."
    payload = raw[len(_NG_MAGIC) :]
    legacy_b64 = base64.b64encode(payload).decode("ascii")
    return _dpapi.unprotect_secret(legacy_b64, purpose=purpose)
