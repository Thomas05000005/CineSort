"""Storage de secrets avec migration DPAPI legacy -> DPAPI-NG.

Strategie de migration progressive (V2.3 -> V2.4) :

1. **Lecture** (`load_secret`) :
   - Si blob porte le magic NG -> dechiffrement DPAPI-NG direct.
   - Sinon -> tentative DPAPI legacy via `local_secret_store`.
   - Si lecture legacy reussit -> re-chiffrement automatique en NG +
     persistance via callback (silent re-encrypt).
   - Si fallback legacy desactive (env `CINESORT_DPAPI_LEGACY_FALLBACK=0`)
     -> erreur claire, l'utilisateur doit re-saisir.

2. **Ecriture** (`save_secret`) :
   - TOUJOURS DPAPI-NG, encode base64 pour stockage texte (SQLite TEXT).

3. **Backward compat** :
   - Les helpers exposes (`load_secret`, `save_secret`) ont une signature
     stable, le caller n'a pas a connaitre le format de stockage.
   - L'ancien `cinesort.infra.local_secret_store.protect_secret /
     unprotect_secret` reste intact pour 1 release minimum (lecture
     seule en pratique apres la migration).
   - Feature flag `CINESORT_DPAPI_LEGACY_FALLBACK` (defaut "1"). Si "0",
     on refuse de lire les blobs legacy (utile pour audit de migration).

4. **Migration au demarrage** (`migrate_legacy_blobs_to_ng`) :
   - Scan d'un mapping name -> stored_blob_b64.
   - Pour chaque entree legacy, re-chiffrement silencieux en NG.
   - Retourne le mapping mis a jour pour reecriture settings.json /
     SQLite par le caller. Pas d'IO directe (couche infra
     storage-agnostique).

Pas d'import depuis `cinesort.domain` (verrouillage import-linter).
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from cinesort.infra import local_secret_store as _legacy
from cinesort.infra.security import dpapi_ng as _ng

logger = logging.getLogger(__name__)

# Feature flag : autorise le fallback de lecture DPAPI legacy.
# Defaut "1" pour 1 release minimum (V2.3). Bascule a "0" en V2.5 quand
# tous les secrets existants ont ete migres et les utilisateurs ont
# demarre l'app au moins une fois.
ENV_LEGACY_FALLBACK: str = "CINESORT_DPAPI_LEGACY_FALLBACK"


class SecretStorageError(RuntimeError):
    """Erreur generique de la couche secret_storage (lecture / ecriture)."""


@dataclass(frozen=True)
class LoadResult:
    """Resultat d'un `load_secret` avec metadata de migration.

    Attributes:
        value: Le secret dechiffre (str UTF-8).
        was_legacy: True si le blob d'origine etait DPAPI legacy. Le
            caller doit alors persister `re_encrypted_blob` pour terminer
            la migration silent.
        re_encrypted_blob: Si `was_legacy=True`, le nouveau blob NG
            (base64) a stocker en remplacement de l'ancien.
    """

    value: str
    was_legacy: bool = False
    re_encrypted_blob: Optional[str] = None


def _legacy_fallback_enabled() -> bool:
    return os.environ.get(ENV_LEGACY_FALLBACK, "1") != "0"


def save_secret(name: str, value: str) -> str:
    """Chiffre `value` en DPAPI-NG et retourne le blob base64 a stocker.

    Args:
        name: Identifiant de l'usage (ex. "tmdb_api_key"). Utilise comme
            `purpose` en cas de fallback ecriture legacy (test only).
        value: Secret en clair.

    Returns:
        str : base64 du blob NG (prefixe magic inclus). Pret pour
        stockage SQLite TEXT ou settings.json.

    Raises:
        SecretStorageError: si DPAPI-NG indisponible (rare, Windows
            sans ncrypt.dll).
    """
    if not _ng.dpapi_ng_available():
        raise SecretStorageError(
            "DPAPI-NG indisponible sur cette machine. CineSort exige Windows 10+. Reinstalle ou contacte le support."
        )
    try:
        blob = _ng.protect_dpapi_ng(str(value or "").encode("utf-8"))
    except _ng.DpapiNgOperationError as exc:
        raise SecretStorageError(f"Echec chiffrement DPAPI-NG ({name}): {exc}") from exc
    return base64.b64encode(blob).decode("ascii")


def load_secret(name: str, stored_blob_b64: str) -> LoadResult:
    """Dechiffre un secret, en migrant transparently de legacy vers NG.

    Args:
        name: Identifiant de l'usage (ex. "tmdb_api_key"). Sert de
            `purpose` pour le dechiffrement legacy (entropy DPAPI).
        stored_blob_b64: Blob base64 lu depuis SQLite / settings.json.

    Returns:
        LoadResult : .value contient le secret en clair. Si
        .was_legacy=True, le caller DOIT persister .re_encrypted_blob
        en remplacement de l'ancienne valeur (sinon la migration
        repete a chaque demarrage, sans casser pour autant).

    Raises:
        SecretStorageError: si le secret est illisible (typique apres
            reinstall Windows / changement de profil). Message clair
            pour le caller (ex. UI Reglages : "re-saisis ta cle").
    """
    if not stored_blob_b64:
        raise SecretStorageError(f"Secret '{name}' vide ou absent.")

    try:
        blob = base64.b64decode(stored_blob_b64.encode("ascii"), validate=True)
    except (TypeError, ValueError) as exc:
        raise SecretStorageError(f"Secret '{name}' base64 invalide: {exc}") from exc

    # Route 1 : blob deja en DPAPI-NG.
    if _ng.is_dpapi_ng_blob(blob):
        if not _ng.dpapi_ng_available():
            raise SecretStorageError("DPAPI-NG indisponible pour relire un secret deja migre.")
        try:
            plaintext = _ng.unprotect_dpapi_ng(blob)
        except _ng.DpapiNgOperationError as exc:
            raise SecretStorageError(
                f"Secret '{name}' illisible (DPAPI-NG). "
                "Possible apres reinstallation Windows ou changement de profil. "
                f"Re-saisis dans Reglages. Detail: {exc}"
            ) from exc
        try:
            return LoadResult(value=plaintext.decode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise SecretStorageError(f"Secret '{name}' non UTF-8: {exc}") from exc

    # Route 2 : blob legacy. Fallback gere par feature flag.
    if not _legacy_fallback_enabled():
        raise SecretStorageError(
            f"Secret '{name}' stocke en DPAPI legacy mais fallback desactive "
            f"(CINESORT_DPAPI_LEGACY_FALLBACK=0). Re-saisis dans Reglages."
        )

    ok, value, err = _legacy.unprotect_secret(stored_blob_b64, purpose=name)
    if not ok:
        raise SecretStorageError(
            f"Secret '{name}' illisible (DPAPI legacy). "
            "Possible apres reinstallation Windows ou changement de profil. "
            f"Re-saisis dans Reglages. Detail: {err}"
        )

    # Re-chiffrement silencieux en DPAPI-NG (si dispo).
    if _ng.dpapi_ng_available():
        try:
            new_blob_b64 = save_secret(name, value)
            logger.info(
                "Secret '%s' migre DPAPI legacy -> DPAPI-NG (silent re-encrypt).",
                name,
            )
            return LoadResult(value=value, was_legacy=True, re_encrypted_blob=new_blob_b64)
        except SecretStorageError as exc:
            # On a la valeur en clair, on accepte de la rendre meme si
            # la re-encryption echoue : le caller pourra reessayer plus
            # tard. Mieux que de bloquer l'app pour un detail.
            logger.warning(
                "Secret '%s' lu en legacy mais re-encrypt NG a echoue: %s",
                name,
                exc,
            )

    return LoadResult(value=value, was_legacy=True, re_encrypted_blob=None)


def migrate_legacy_blobs_to_ng(
    stored: Dict[str, str],
    *,
    on_migrated: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, str]:
    """Scan d'un mapping name -> blob_b64 et migration silent en NG.

    ETAT REEL : cette fonction n'a AUCUN appelant (verifie sur `cinesort/`,
    `tests/` et `app.py` — ses seules occurrences sont sa definition, cette
    docstring et `__all__`). La migration effective se fait secret par secret au
    prochain SAVE (`settings_support.py`), ou c'est explicitement assume. Elle
    est conservee, pas branchee : le retrait d'un symbole de securite se decide,
    il ne se glisse pas dans un correctif de docstring.

    Le contrat ci-dessous a ete CORRIGE parce qu'il decrivait l'inverse du code.
    Il annoncait « le mapping retourne EST le meme objet (mute) — comparer
    l'identite des blobs pour decider si une persistance est necessaire ». Or le
    code fait `updated = dict(stored)`, donc une COPIE : mesure, `retour is
    entree` rend `False` des que `stored` est non vide (le raccourci du cas vide,
    lui, rend bien le meme objet). Un appelant qui aurait suivi la recette
    documentee aurait persiste a CHAQUE demarrage, sans qu'aucun secret n'ait
    change.

    Pour decider s'il faut persister, comparer donc les VALEURS
    (`updated != stored`), ou se fier au callback `on_migrated`.

    Args:
        stored: { name: blob_b64 } actuel.
        on_migrated: callback optionnel appele a chaque migration reussie
            avec (name, new_blob_b64). Permet une persistance immediate
            sans attendre la fin du scan (utile si beaucoup de secrets).

    Returns:
        Dict[str, str] : mapping mis a jour. Les secrets illisibles
        sont conserves tels quels (legacy) ; ils declencheront une
        SecretStorageError lors du prochain `load_secret`.
    """
    if not stored:
        return stored
    updated: Dict[str, str] = dict(stored)
    for name, blob_b64 in stored.items():
        try:
            result = load_secret(name, blob_b64)
        except SecretStorageError as exc:
            logger.warning(
                "Migration secret '%s' impossible (sera retentee au prochain load): %s",
                name,
                exc,
            )
            continue
        if result.was_legacy and result.re_encrypted_blob:
            updated[name] = result.re_encrypted_blob
            if on_migrated is not None:
                try:
                    on_migrated(name, result.re_encrypted_blob)
                except Exception:  # pragma: no cover - callback user-defined
                    logger.exception("Callback on_migrated a leve pour '%s'", name)
    return updated


__all__ = [
    "ENV_LEGACY_FALLBACK",
    "LoadResult",
    "SecretStorageError",
    "load_secret",
    "migrate_legacy_blobs_to_ng",
    "save_secret",
]
