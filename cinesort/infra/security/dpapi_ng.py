"""Wrapper Python ctypes pour DPAPI-NG (NCryptProtectSecret / NCryptUnprotectSecret).

DPAPI-NG (Cryptography Next Generation, Vista+) remplace l'ancien
CryptProtectData/CryptUnprotectData (crypt32.dll) par les APIs Ncrypt
(ncrypt.dll). Avantages :

- SHA-256+ par defaut (FIPS 140-2 compliant).
- Protection descriptor SID-based : on cible explicitement le SID
  de l'utilisateur courant (LOCAL=user), ce qui est plus auditable
  que CRYPTPROTECT_UI_FORBIDDEN.
- Compatible Windows 10/11 entreprise (FIPS mode active sans rejet).
- Extensible : meme API peut cibler un groupe AD, une cle DPAPI-NG
  centralisee, etc. (non utilise ici, scope local user uniquement).

BACKWARD COMPAT :
- Cette fonction ne casse PAS DPAPI legacy : les blobs legacy doivent
  etre dechiffres via cinesort.infra.local_secret_store puis
  re-chiffres ici. Voir secret_storage.load_secret().
- Tag de format : tout blob ecrit par protect_dpapi_ng() est prefixe
  par CINESORT_DPAPI_NG_MAGIC pour pouvoir distinguer legacy vs NG
  sans tentative de dechiffrement couteuse.

Refs :
- https://learn.microsoft.com/en-us/windows/win32/api/ncrypt/nf-ncrypt-ncryptprotectsecret
- https://learn.microsoft.com/en-us/windows/win32/api/ncrypt/nf-ncrypt-ncryptunprotectsecret
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Final

# Magic bytes : permet a secret_storage de distinguer un blob NG d'un blob legacy
# sans tentative de dechiffrement. 8 octets aleatoires fixes (ne PAS changer).
CINESORT_DPAPI_NG_MAGIC: Final[bytes] = b"CSNG\x01\x00\x00\x00"

# Protection descriptor : SID de l'utilisateur courant.
# "LOCAL=user" -> equivalent CURRENT_USER, scope identique au DPAPI legacy.
# Voir https://learn.microsoft.com/en-us/windows/win32/seccng/protection-descriptors
_NCRYPT_DESCRIPTOR_LOCAL_USER: Final[str] = "LOCAL=user"

# Flags NCryptProtectSecret : UI_FORBIDDEN pour eviter tout prompt UI
# pendant un appel headless (ex. demarrage du daemon).
_NCRYPT_SILENT_FLAG: Final[int] = 0x00000040  # NCRYPT_SILENT_FLAG


class DpapiNgUnavailableError(RuntimeError):
    """Leve si ncrypt.dll est introuvable ou si l'OS ne supporte pas DPAPI-NG."""


class DpapiNgOperationError(RuntimeError):
    """Leve si NCryptProtectSecret / NCryptUnprotectSecret echoue."""


def dpapi_ng_available() -> bool:
    """Retourne True si DPAPI-NG est utilisable sur la machine courante.

    DPAPI-NG est dispo sur Windows Vista+, donc en pratique toujours True
    sur les cibles CineSort (Windows 10+). On garde le check defensif au
    cas ou ncrypt.dll serait absente (Windows Server Core sans crypto).
    """
    if os.name != "nt":
        return False
    if not hasattr(ctypes, "windll"):
        return False
    try:
        _load_ncrypt()
        return True
    except DpapiNgUnavailableError:
        return False


def _load_ncrypt():
    """Charge ncrypt.dll et configure les signatures des APIs utilisees."""
    try:
        ncrypt = ctypes.windll.ncrypt
    except (AttributeError, OSError) as exc:
        raise DpapiNgUnavailableError(f"ncrypt.dll indisponible: {exc}") from exc

    # SECURITY_STATUS NCryptCreateProtectionDescriptor(
    #   LPCWSTR pwszDescriptorString, DWORD dwFlags,
    #   NCRYPT_DESCRIPTOR_HANDLE *phDescriptor)
    ncrypt.NCryptCreateProtectionDescriptor.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ncrypt.NCryptCreateProtectionDescriptor.restype = ctypes.c_long

    # SECURITY_STATUS NCryptCloseProtectionDescriptor(
    #   NCRYPT_DESCRIPTOR_HANDLE hDescriptor)
    ncrypt.NCryptCloseProtectionDescriptor.argtypes = [ctypes.c_void_p]
    ncrypt.NCryptCloseProtectionDescriptor.restype = ctypes.c_long

    # SECURITY_STATUS NCryptProtectSecret(
    #   NCRYPT_DESCRIPTOR_HANDLE hDescriptor, DWORD dwFlags,
    #   const BYTE *pbData, ULONG cbData,
    #   const NCRYPT_ALLOC_PARA *pMemPara, HWND hWnd,
    #   BYTE **ppbProtectedBlob, ULONG *pcbProtectedBlob)
    ncrypt.NCryptProtectSecret.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_ubyte),
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.HWND,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
        ctypes.POINTER(wintypes.ULONG),
    ]
    ncrypt.NCryptProtectSecret.restype = ctypes.c_long

    # SECURITY_STATUS NCryptUnprotectSecret(
    #   NCRYPT_DESCRIPTOR_HANDLE *phDescriptor, DWORD dwFlags,
    #   const BYTE *pbProtectedBlob, ULONG cbProtectedBlob,
    #   const NCRYPT_ALLOC_PARA *pMemPara, HWND hWnd,
    #   BYTE **ppbData, ULONG *pcbData)
    ncrypt.NCryptUnprotectSecret.argtypes = [
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_ubyte),
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.HWND,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
        ctypes.POINTER(wintypes.ULONG),
    ]
    ncrypt.NCryptUnprotectSecret.restype = ctypes.c_long

    # kernel32.LocalFree : libere les buffers alloues par NCrypt*.
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    return ncrypt, kernel32


def _check_status(status: int, op: str) -> None:
    """Convertit un SECURITY_STATUS != 0 en exception lisible."""
    if status != 0:
        # SECURITY_STATUS est un HRESULT-like ; on l'expose tel quel.
        raise DpapiNgOperationError(
            f"{op} a echoue (NTSTATUS=0x{status & 0xFFFFFFFF:08X})"
        )


def protect_dpapi_ng(plaintext: bytes) -> bytes:
    """Chiffre `plaintext` via DPAPI-NG (SID utilisateur courant, SHA-256+).

    Le blob retourne est prefixe de CINESORT_DPAPI_NG_MAGIC (8 octets)
    pour pouvoir distinguer un blob NG d'un blob legacy a la lecture
    sans tentative de dechiffrement couteuse.

    Args:
        plaintext: Donnees en clair a proteger (bytes brut, pas de base64).

    Returns:
        bytes : magic (8) + blob NCrypt protege. A persister tel quel
        (ex. base64 avant ecriture SQLite, fait par secret_storage).

    Raises:
        DpapiNgUnavailableError: si ncrypt.dll est inaccessible.
        DpapiNgOperationError: si NCryptProtectSecret echoue.
    """
    if not isinstance(plaintext, (bytes, bytearray)):
        raise TypeError("plaintext doit etre bytes")

    ncrypt, kernel32 = _load_ncrypt()

    descriptor = ctypes.c_void_p()
    status = ncrypt.NCryptCreateProtectionDescriptor(
        _NCRYPT_DESCRIPTOR_LOCAL_USER, 0, ctypes.byref(descriptor)
    )
    _check_status(status, "NCryptCreateProtectionDescriptor")

    try:
        if plaintext:
            buf = (ctypes.c_ubyte * len(plaintext)).from_buffer_copy(bytes(plaintext))
            data_ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
        else:
            buf = None
            data_ptr = ctypes.POINTER(ctypes.c_ubyte)()

        out_ptr = ctypes.POINTER(ctypes.c_ubyte)()
        out_len = wintypes.ULONG(0)

        status = ncrypt.NCryptProtectSecret(
            descriptor,
            _NCRYPT_SILENT_FLAG,
            data_ptr,
            wintypes.ULONG(len(plaintext)),
            None,
            None,
            ctypes.byref(out_ptr),
            ctypes.byref(out_len),
        )
        _check_status(status, "NCryptProtectSecret")
        del buf  # garder le buffer source vivant jusqu'ici

        try:
            blob = ctypes.string_at(out_ptr, out_len.value)
            return CINESORT_DPAPI_NG_MAGIC + blob
        finally:
            if out_ptr:
                kernel32.LocalFree(ctypes.cast(out_ptr, wintypes.HLOCAL))
    finally:
        ncrypt.NCryptCloseProtectionDescriptor(descriptor)


def unprotect_dpapi_ng(ciphertext: bytes) -> bytes:
    """Dechiffre un blob produit par `protect_dpapi_ng`.

    Args:
        ciphertext: bytes commencant par CINESORT_DPAPI_NG_MAGIC.

    Returns:
        bytes : plaintext original.

    Raises:
        ValueError: si le blob ne porte pas le magic NG (cas legacy).
        DpapiNgUnavailableError: si ncrypt.dll est inaccessible.
        DpapiNgOperationError: si NCryptUnprotectSecret echoue (typique
            apres reinstall Windows / changement de profil utilisateur).
    """
    if not isinstance(ciphertext, (bytes, bytearray)):
        raise TypeError("ciphertext doit etre bytes")
    if not is_dpapi_ng_blob(ciphertext):
        raise ValueError(
            "Blob non-NG : magic CINESORT_DPAPI_NG absent, "
            "utiliser local_secret_store.unprotect_secret() pour legacy."
        )

    ncrypt, kernel32 = _load_ncrypt()

    payload = bytes(ciphertext[len(CINESORT_DPAPI_NG_MAGIC):])
    if payload:
        buf = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
        in_ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
    else:
        buf = None
        in_ptr = ctypes.POINTER(ctypes.c_ubyte)()

    out_ptr = ctypes.POINTER(ctypes.c_ubyte)()
    out_len = wintypes.ULONG(0)
    descriptor = ctypes.c_void_p()

    status = ncrypt.NCryptUnprotectSecret(
        ctypes.byref(descriptor),
        _NCRYPT_SILENT_FLAG,
        in_ptr,
        wintypes.ULONG(len(payload)),
        None,
        None,
        ctypes.byref(out_ptr),
        ctypes.byref(out_len),
    )
    _check_status(status, "NCryptUnprotectSecret")
    del buf

    try:
        plaintext = ctypes.string_at(out_ptr, out_len.value)
        return plaintext
    finally:
        if out_ptr:
            kernel32.LocalFree(ctypes.cast(out_ptr, wintypes.HLOCAL))
        if descriptor:
            ncrypt.NCryptCloseProtectionDescriptor(descriptor)


def is_dpapi_ng_blob(blob: bytes) -> bool:
    """True si `blob` commence par CINESORT_DPAPI_NG_MAGIC.

    Utilise par secret_storage pour router lecture NG vs legacy sans
    tentative de dechiffrement (qui ferait sortir une exception Windows
    couteuse a tracer dans les logs).
    """
    if not isinstance(blob, (bytes, bytearray)):
        return False
    return bytes(blob[: len(CINESORT_DPAPI_NG_MAGIC)]) == CINESORT_DPAPI_NG_MAGIC


__all__ = [
    "CINESORT_DPAPI_NG_MAGIC",
    "DpapiNgOperationError",
    "DpapiNgUnavailableError",
    "dpapi_ng_available",
    "is_dpapi_ng_blob",
    "protect_dpapi_ng",
    "unprotect_dpapi_ng",
]
