"""Utilitaires reseau — detection IP locale pour le dashboard distant."""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Cf issue #70 : hosts metadata cloud que les URLs Jellyfin/Plex/Radarr ne
# doivent jamais cibler. Si un attaquant distant LAN reconfigure les URLs
# via REST API, il pourrait scanner ces endpoints internes.
_CLOUD_METADATA_HOSTS = frozenset(
    {
        "169.254.169.254",  # AWS, Azure, OpenStack
        "fd00:ec2::254",  # AWS IPv6
        "metadata.google.internal",  # GCP
        "metadata",  # GCP short
        "instance-data.ec2.internal",  # AWS DNS
        "metadata.azure.com",  # Azure
    }
)


def is_safe_external_url(url: str) -> Tuple[bool, str]:
    """Cf issue #70 : valide qu'une URL externe (Jellyfin/Plex/Radarr/etc.) ne
    cible pas un endpoint cloud metadata sensible.

    Retourne (True, "") si OK, (False, reason) sinon.

    Politique :
    - scheme MUST be http ou https (refuse file:, ftp:, gopher:, etc.)
    - host MUST NOT etre dans _CLOUD_METADATA_HOSTS (169.254.169.254 etc.)
    - host MUST NOT etre dans 169.254.0.0/16 (link-local IPv4)

    Note : localhost / IPs privees (127.x, 10.x, 192.168.x) sont AUTORISES
    car un user perso peut avoir Plex sur la meme machine que CineSort. Le
    SSRF reel concerne les metadata cloud, pas le LAN domestique.
    """
    if not url or not isinstance(url, str):
        return False, "URL vide"
    try:
        parsed = urlparse(url.strip())
    except ValueError as exc:
        return False, f"URL invalide ({exc})"
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        return False, f"Scheme '{scheme}' interdit (http/https uniquement)"
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "Host absent"
    if host in _CLOUD_METADATA_HOSTS:
        return False, f"Host '{host}' interdit (cloud metadata)"
    # Bloquer le bloc link-local IPv4 169.254.0.0/16
    try:
        ip = ipaddress.ip_address(host)
        if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.IPv4Network("169.254.0.0/16"):
            return False, f"Host '{host}' interdit (link-local IPv4)"
    except ValueError:
        pass  # host n'est pas une IP litterale, c'est un FQDN — OK
    return True, ""


def get_local_ip() -> str:
    """Detecte l'IP LAN locale via la technique UDP socket (stdlib, pas de requete reseau).

    Fallback 1 : gethostbyname(gethostname())
    Fallback 2 : 127.0.0.1
    Ne crash jamais.
    """
    # Technique UDP : connecter un socket UDP vers une IP publique
    # (aucun paquet n'est envoye, seul le bind local est effectue)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and ip != "0.0.0.0":
                logger.info("network: IP locale detectee = %s (UDP)", ip)
                return ip
    except OSError:
        pass

    # Fallback : resolution hostname
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and ip != "127.0.1.1":
            logger.info("network: IP locale detectee = %s (hostname)", ip)
            return ip
    except OSError:
        pass

    logger.info("network: IP locale non detectee, fallback 127.0.0.1")
    return "127.0.0.1"


def build_dashboard_url(ip: str, port: int, https: bool = False) -> str:
    """Construit l'URL complete du dashboard distant."""
    proto = "https" if https else "http"
    return f"{proto}://{ip}:{port}/dashboard/"
