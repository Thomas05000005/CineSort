"""Couche de protection des secrets settings (DPAPI-NG + retro-compat legacy).

Ce package regroupe le stockage chiffre des cles API / tokens
(TMDb, Jellyfin, Plex, Radarr, SMTP, token REST) :

- `dpapi_ng`      : enveloppe DPAPI-NG (marqueur + charge protegee).
- `secret_storage`: facade `save_secret` / `load_secret` avec routage
  transparent NG (nouveau format) vs legacy (blob DPAPI CURRENT_USER
  historique deja present dans un settings.json existant).

La cryptographie effective delegue a `cinesort.infra.local_secret_store`
(DPAPI Windows CURRENT_USER via crypt32). Sur les plateformes sans DPAPI
(Linux/macOS CI), `protection_available()` est False : `save_secret` leve
`SecretStorageError` et l'appelant retombe sur la protection legacy.
"""

from __future__ import annotations
