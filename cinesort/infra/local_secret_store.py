from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes
from typing import Tuple


WINDOWS_DPAPI_CURRENT_USER = "windows_dpapi_current_user"
SECRET_PROTECTION_UNAVAILABLE = "unavailable"
SECRET_PROTECTION_NONE = "none"

_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def protection_available() -> bool:
    return os.name == "nt" and hasattr(ctypes, "windll")


def _blob_from_bytes(data: bytes) -> Tuple[_DataBlob, object | None]:
    if not data:
        return _DataBlob(0, None), None
    buf = ctypes.create_string_buffer(data)
    ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
    return _DataBlob(len(data), ptr), buf


def _purpose_entropy(purpose: str) -> bytes:
    return f"CineSort::{purpose}::v1".encode("utf-8")


def _protect_bytes(raw: bytes, *, purpose: str) -> Tuple[bool, str, str]:
    if not protection_available():
        return False, "", "Windows DPAPI non disponible."

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    input_blob, input_ref = _blob_from_bytes(raw)
    entropy_blob, entropy_ref = _blob_from_bytes(_purpose_entropy(purpose))
    del input_ref, entropy_ref
    output_blob = _DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        purpose,
        ctypes.byref(entropy_blob),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    if not ok:
        return False, "", str(ctypes.WinError())

    try:
        payload = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return True, base64.b64encode(payload).decode("ascii"), ""
    finally:
        if output_blob.pbData:
            kernel32.LocalFree(output_blob.pbData)


def _unprotect_bytes(blob_b64: str, *, purpose: str) -> Tuple[bool, bytes, str]:
    if not protection_available():
        return False, b"", "Windows DPAPI non disponible."

    try:
        protected = base64.b64decode(blob_b64.encode("ascii"), validate=True)
    except (TypeError, ValueError) as exc:
        return False, b"", f"Secret protege invalide: {exc}"

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    input_blob, input_ref = _blob_from_bytes(protected)
    entropy_blob, entropy_ref = _blob_from_bytes(_purpose_entropy(purpose))
    del input_ref, entropy_ref
    output_blob = _DataBlob()
    description = wintypes.LPWSTR()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        ctypes.byref(description),
        ctypes.byref(entropy_blob),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    if not ok:
        return False, b"", str(ctypes.WinError())

    try:
        payload = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return True, payload, ""
    finally:
        if description:
            kernel32.LocalFree(description)
        if output_blob.pbData:
            kernel32.LocalFree(output_blob.pbData)


def protect_secret(value: str, *, purpose: str) -> Tuple[bool, str, str]:
    """Chiffre un secret via DPAPI Windows (scope CURRENT_USER).

    SCOPE EFFECTIF : CURRENT_USER (defaut DPAPI sans flag
    CRYPTPROTECT_LOCAL_MACHINE). La cle de chiffrement est derivee du
    mot de passe utilisateur Windows + identifiant machine.

    CONSEQUENCES IMPORTANTES :
    - Reinstall Windows -> les secrets ne se dechiffrent plus.
    - Reset password admin via rescue mode -> idem.
    - Export DB vers une autre machine ou un autre profil utilisateur
      -> secrets illisibles, l'utilisateur doit re-saisir les cles API
      (TMDb, Jellyfin, Plex, Radarr).
    - Roaming profile : le profil utilisateur doit etre intact.

    Ce comportement est volontaire : un attaquant qui copie le fichier
    DB sur sa machine ne peut PAS lire les secrets. C'est aussi
    pourquoi on ne stocke jamais les secrets en clair.

    Pour les setups multi-utilisateurs sur la meme machine (ex. PC
    familial partage), un futur parametre prefer_machine_scope=True
    pourrait basculer sur CRYPTPROTECT_LOCAL_MACHINE (cle derivee de
    la machine seule, accessible a tous les utilisateurs locaux).
    Pas implemente car cas d'usage marginal et reduit la securite.

    Args:
        value: La valeur secrete a chiffrer (cle API, token).
        purpose: Identifiant unique d'usage (ex. "tmdb_api_key").
            Inclus dans l'entropie pour empecher la reutilisation
            d'un blob entre purposes distincts.

    Returns:
        (ok, blob_b64, error) : si ok=True, blob_b64 contient le
        secret chiffre encode base64 (pret pour stockage SQLite).

    See Also:
        https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata
    """
    raw = str(value or "").encode("utf-8")
    return _protect_bytes(raw, purpose=purpose)


def unprotect_secret(blob_b64: str, *, purpose: str) -> Tuple[bool, str, str]:
    """Dechiffre un secret protege par protect_secret.

    Si le dechiffrement echoue, cela signifie typiquement que le scope
    DPAPI CURRENT_USER a change (reinstall Windows, reset password,
    copie DB sur autre machine). Le caller DOIT loguer un message
    clair a l'utilisateur du style :

        "Secret <X> illisible. Cela peut arriver apres une reinstallation
         Windows ou si la base est copiee depuis un autre PC. Re-saisis
         la cle dans Reglages."

    Args:
        blob_b64: Le secret chiffre encode base64 (issu de protect_secret).
        purpose: Identifiant d'usage (DOIT matcher celui de protect_secret).

    Returns:
        (ok, value, error) : si ok=True, value contient le secret en
        clair (string UTF-8). Si ok=False, error contient un message
        Windows DPAPI ou "Secret protege non UTF-8".
    """
    ok, payload, error = _unprotect_bytes(blob_b64, purpose=purpose)
    if not ok:
        return False, "", error
    try:
        return True, payload.decode("utf-8"), ""
    except (TypeError, ValueError) as exc:
        return False, "", f"Secret protege non UTF-8: {exc}"
