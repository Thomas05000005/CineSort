"""Utilitaires reseau — detection IP locale + politique d'adresse SSRF.

La politique d'adresse (`blocked_ip_reason`) est partagee par deux points de
controle : la validation d'URL en amont (`is_safe_external_url`) et la
verification du pair reellement joint par la socket
(`cinesort.infra._http_utils`). Seule la seconde ferme le DNS rebinding.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import List, Optional, Tuple, Union
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]

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


def _parse_ip(value: str) -> Optional[_IPAddress]:
    """Parse une IP litterale, ou None si `value` n'en est pas une (FQDN, vide...)."""
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


# Sous-ensemble IP litterales de _CLOUD_METADATA_HOSTS : c'est contre CES IP que
# l'on compare le resultat d'une resolution DNS (le NOM, lui, est deja refuse
# lexicalement plus haut). `fd00:ec2::254` est une ULA (fc00::/7), PAS une
# link-local — sans cette liste explicite, un FQDN resolvant vers cette IP
# passerait au travers du seul test `is_link_local`.
_BLOCKED_METADATA_IPS = frozenset(ip for ip in (_parse_ip(h) for h in _CLOUD_METADATA_HOSTS) if ip is not None)


class BlockedAddressError(OSError):
    """Connexion refusee : l'adresse distante est interdite par la politique SSRF.

    Herite d'`OSError` volontairement : urllib3 et requests traitent alors le
    refus comme une erreur de connexion ordinaire (message propage jusqu'au
    caller) au lieu de laisser fuiter une exception inconnue a travers la pile
    HTTP. Cf `cinesort.infra._http_utils` pour le point de controle.
    """


def blocked_ip_reason(address: object) -> str:
    """Retourne un motif NON VIDE si `address` est interdite, `""` si elle est permise.

    Politique (identique pour une IP litterale d'URL et pour l'adresse reellement
    jointe par une socket) :
    - link-local IPv4 169.254.0.0/16 et IPv6 fe80::/10 — couvre 169.254.169.254 ;
    - IP litterales de `_CLOUD_METADATA_HOSTS` (dont l'ULA `fd00:ec2::254`) ;
    - les IPv4-mapped IPv6 (`::ffff:169.254.169.254`) sont normalisees avant test.

    Le LAN et la loopback restent AUTORISES : c'est le modele de menace assume du
    produit (l'utilisateur heberge legitimement Plex/Jellyfin sur sa machine).

    Fail-closed : une adresse illisible (vide, None, format inconnu) est refusee —
    on ne laisse pas passer ce qu'on ne sait pas lire.
    """
    ip: Optional[_IPAddress]
    if isinstance(address, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        ip = address
    else:
        ip = _parse_ip(str(address or "").strip())
    if ip is None:
        return f"adresse '{address}' illisible (refus par defaut)"
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # L'ordre compte : 169.254.169.254 est A LA FOIS link-local et metadata ;
    # on annonce "link-local", le motif le plus general.
    if ip.is_link_local:
        return f"IP {ip} interdite (link-local)"
    if ip in _BLOCKED_METADATA_IPS:
        return f"IP {ip} interdite (metadata cloud)"
    return ""


def _resolve_host_addresses(host: str) -> List[str]:
    """Resout `host` en liste d'IP (v4 + v6). Passe par le module pour etre mockable."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return [str(info[4][0]) for info in infos if info[4]]


def _check_fqdn_resolution(host: str) -> Tuple[bool, str]:
    """Cf issue #624 : refuse un FQDN dont la resolution DNS pointe vers une IP interdite.

    Refuse des qu'UNE SEULE adresse renvoyee est interdite (et non « toutes ») :
    un resolveur hostile qui alterne entre une IP publique et 169.254.169.254 doit
    etre refuse, pas tire au sort.
    """
    try:
        addresses = _resolve_host_addresses(host)
    except (OSError, ValueError) as exc:
        # gaierror herite d'OSError. On NE refuse PAS : un nom temporairement
        # non resolvable (serveur eteint, PC hors ligne au moment ou l'utilisateur
        # saisit l'URL de son Jellyfin) doit rester configurable. Le refus n'est
        # pas silencieux — il est trace — et la garde de connexion
        # (_http_utils.SsrfGuardHTTPAdapter) reste, elle, en vigueur au moment ou
        # la connexion est reellement etablie.
        logger.warning(
            "network: resolution DNS impossible pour '%s' (%s) — verification de l'IP reportee a la connexion",
            host,
            exc,
        )
        return True, ""
    for address in addresses:
        reason = blocked_ip_reason(address)
        if reason:
            return False, f"Host '{host}' resout vers une adresse interdite ({reason})"
    return True, ""


def is_safe_external_url(url: str, *, resolve_dns: bool = True) -> Tuple[bool, str]:
    """Cf issue #70 : valide qu'une URL externe (Jellyfin/Plex/Radarr/etc.) ne
    cible pas un endpoint cloud metadata sensible.

    Retourne (True, "") si OK, (False, reason) sinon.

    Politique :
    - scheme MUST be http ou https (refuse file:, ftp:, gopher:, etc.)
    - host MUST NOT etre dans _CLOUD_METADATA_HOSTS (169.254.169.254 etc.)
    - host MUST NOT etre link-local (169.254.0.0/16 IPv4, fe80::/10 IPv6)
    - si `resolve_dns` (defaut) et que le host est un FQDN : sa resolution DNS
      ne doit ramener AUCUNE adresse interdite (issue #624).

    Note : localhost / IPs privees (127.x, 10.x, 192.168.x) sont AUTORISES
    car un user perso peut avoir Plex sur la meme machine que CineSort. Le
    SSRF reel concerne les metadata cloud, pas le LAN domestique.

    PORTEE EXACTE de la verification DNS (issue #624) — a lire avant d'annoncer
    CWE-918 clos :
    - CE QUI EST FERME ici : un FQDN dont les enregistrements A/AAAA pointent
      vers une IP interdite AU MOMENT DE LA VALIDATION (attaque « statique » et
      mauvaise configuration accidentelle).
    - CE QUI N'EST PAS FERME ici : le DNS rebinding proprement dit. Entre cette
      resolution et le `connect()` de `requests`, l'attaquant peut changer son
      enregistrement (TTL 0) : c'est un TOCTOU inherent a toute validation faite
      en amont de la connexion. Cette fenetre est fermee AILLEURS, par
      `cinesort.infra._http_utils.SsrfGuardHTTPAdapter`, qui verifie l'adresse
      REELLEMENT jointe par la socket avant qu'un seul octet ne soit emis.
      Appeler cette fonction seule ne protege donc PAS du rebinding.
    - `resolve_dns=False` desactive la resolution (validation purement lexicale) :
      utile pour un appelant qui ne veut pas d'E/S reseau.
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
    # Bloquer le link-local (169.254.0.0/16 IPv4 ET fe80::/10 IPv6), qui couvre
    # l'endpoint metadata cloud 169.254.169.254 et l'auto-configuration. La
    # normalisation IPv4-mapped IPv6 (::ffff:169.254.169.254, #733) est faite
    # dans blocked_ip_reason.
    literal_ip = _parse_ip(host)
    if literal_ip is not None:
        reason = blocked_ip_reason(literal_ip)
        if reason:
            return False, f"Host '{host}' interdit ({reason})"
        return True, ""
    # host n'est pas une IP litterale : c'est un FQDN. Cf issue #624 — la
    # validation lexicale seule laissait passer un nom pointant vers le LAN
    # ou vers 169.254.169.254.
    if not resolve_dns:
        return True, ""
    return _check_fqdn_resolution(host)


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
