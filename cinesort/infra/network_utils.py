"""Utilitaires reseau — detection IP locale pour le dashboard distant."""

from __future__ import annotations

import logging
import socket

logger = logging.getLogger(__name__)


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
