"""Couche securite CineSort (DPAPI-NG, secret storage, Windows Hello gate).

BACKWARD COMPAT (V2.3 -> V2.4) :
- DPAPI legacy (cinesort/infra/local_secret_store.py) reste fonctionnel.
- Toute migration vers DPAPI-NG est progressive : lecture transparente
  des deux formats, ecriture exclusivement en NG, re-chiffrement silent
  des blobs legacy detectes au demarrage.
- Feature flag CINESORT_DPAPI_LEGACY_FALLBACK=1 (defaut) maintient le
  fallback de lecture DPAPI legacy au moins 1 release.

Ne PAS importer depuis cinesort.domain (verrouillage import-linter).
"""

from __future__ import annotations

__all__ = [
    "dpapi_ng",
    "secret_storage",
    "windows_hello_gate",
]
